from collections import Counter, defaultdict, OrderedDict

from geopy.distance import VincentyDistance
from pockets.autolog import log
from pytz import UTC
import six
from sqlalchemy import and_, func
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import literal

from uber.config import c
from uber.decorators import ajax, all_renderable, csv_file, not_site_mappable
from uber.jinja import JinjaEnv
from uber.models import Attendee, Group, PromoCode, Tracking
from uber.utils import localize_datetime


@JinjaEnv.jinja_filter
def get_count(counter, key):
    return counter.get(key)


def date_trunc_hour(*args, **kwargs):
    # sqlite doesn't support date_trunc
    if c.SQLALCHEMY_URL.startswith('sqlite'):
        return func.strftime(literal('%Y-%m-%d %H:00'), *args, **kwargs)
    else:
        return func.date_trunc(literal('hour'), *args, **kwargs)


class RegistrationDataOneYear:
    def __init__(self):
        self.event_name = ""

        # what is the final day of this event (i.e. Sunday of a Fri->Sun festival)
        self.end_date = ""

        # this holds how many registrations were taken each day starting at 365 days from the end date of the event.
        # this array is in chronological order and does not skip days.
        #
        # examples:
        # registrations_per_day[0]   is the #regs that were taken on end_date-365 (1 year before the event)
        # .....
        # registrations_per_day[362] is the #regs that were taken on end_date-2 (2 days before the end date)
        # registrations_per_day[363] is the #regs that were taken on end_date-1 (the day before the end date)
        # registrations_per_day[364] is the #regs that were taken on end_date
        self.registrations_per_day = []

        # same as above, but, contains a cumulative sum of the same data
        self.registrations_per_day_cumulative_sum = []

        self.num_days_to_report = 365

    def query_current_year(self, session):
        self.event_name = c.EVENT_NAME_AND_YEAR

        # TODO: we're hacking the timezone info out of ESCHATON (final day of event). probably not the right thing to do
        self.end_date = c.DATES['ESCHATON'].replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)

        def date_trunc_day(*args, **kwargs):
            # sqlite doesn't support date_trunc
            if c.SQLALCHEMY_URL.startswith('sqlite'):
                return func.date(*args, **kwargs)
            else:
                return func.date_trunc(literal('day'), *args, **kwargs)

        # return registrations where people actually paid money
        # exclude: dealers
        reg_per_day = session.query(
                date_trunc_day(Attendee.registered),
                func.count(date_trunc_day(Attendee.registered))
            ) \
            .outerjoin(Attendee.group) \
            .filter(
                (
                    (Attendee.group_id != None) &
                    (Attendee.paid == c.PAID_BY_GROUP) &  # if they're paid by group
                    (Group.tables == 0) &                 # make sure they aren't dealers
                    (Group.amount_paid > 0)               # make sure they've paid something
                ) | (                                     # OR
                    (Attendee.paid == c.HAS_PAID)         # if they're an attendee, make sure they're fully paid
                )
            ) \
            .group_by(date_trunc_day(Attendee.registered)) \
            .order_by(date_trunc_day(Attendee.registered)) \
            .all()  # noqa: E711
        
        group_reg_per_day = session.query(
            date_trunc_day(PromoCode.group_registered),
            func.count(date_trunc_day(PromoCode.group_registered))
            ) \
        .filter(PromoCode.cost > 0) \
        .group_by(date_trunc_day(PromoCode.group_registered)) \
        .order_by(date_trunc_day(PromoCode.group_registered)) \
        .all()

        # now, convert the query's data into the format we need.
        # SQL will skip days without registrations
        # we need all self.num_days_to_report days to have data, even if it's zero

        # create 365 elements in the final array
        self.registrations_per_day = self.num_days_to_report * [0]

        # merge attendee and promo code group reg
        total_reg_per_day = defaultdict(int)
        for k, v in dict(reg_per_day).items():
            if not k:
                continue
            total_reg_per_day[k] += v
        for k, v in dict(group_reg_per_day).items():
            if not k:
                continue
            total_reg_per_day[k] += v

        for day, reg_count in total_reg_per_day.items():
            day_offset = self.num_days_to_report - (self.end_date - day).days
            day_index = day_offset - 1

            if day_index < 0 or day_index >= self.num_days_to_report:
                log.info(
                    "Ignoring some analytics data because it's not in range of the year before c.ESCHATON. "
                    "Either c.ESCHATON is set incorrectly or you have registrations starting 1 year before ESCHATON, "
                    "or occuring after ESCHATON. day_index=" + str(day_index))
                continue

            self.registrations_per_day[day_index] = reg_count

        self.compute_cumulative_sum_from_registrations_per_day()

    # compute cumulative sum up until the last non-zero data point
    def compute_cumulative_sum_from_registrations_per_day(self):

        if len(self.registrations_per_day) != self.num_days_to_report:
            raise 'array validation error: array size should be the same as the report size'

        # figure out where the last non-zero data point is in the array
        last_useful_data_index = self.num_days_to_report - 1
        for regs in reversed(self.registrations_per_day):
            if regs != 0:
                break  # found it, so we're done.
            last_useful_data_index -= 1

        # compute the cumulative sum, leaving all numbers past the last data point at zero
        self.registrations_per_day_cumulative_sum = self.num_days_to_report * [0]
        total_so_far = 0
        current_index = 0
        for regs_this_day in self.registrations_per_day:
            total_so_far += regs_this_day
            self.registrations_per_day_cumulative_sum[current_index] = total_so_far
            if current_index == last_useful_data_index:
                break
            current_index += 1

    def dump_data(self):
        return {
            "registrations_per_day": self.registrations_per_day,
            "registrations_per_day_cumulative_sum": self.registrations_per_day_cumulative_sum,
            "event_name": self.event_name,
            "event_end_date": self.end_date.strftime("%d-%m-%Y"),
        }


@all_renderable()
class Root:
    def index(self, session):
        counts = defaultdict(OrderedDict)
        counts['donation_tiers'] = OrderedDict([(k, 0) for k in sorted(c.DONATION_TIERS.keys()) if k > 0])

        counts.update({
            'groups': {'paid': 0, 'free': 0},
            'noshows': {'paid': 0, 'free': 0},
            'checked_in': {'yes': 0, 'no': 0}
        })
        count_labels = {
            'badges': c.BADGE_OPTS,
            'paid': c.PAYMENT_OPTS,
            'ages': c.AGE_GROUP_OPTS,
            'ribbons': c.RIBBON_OPTS,
            'interests': c.INTEREST_OPTS,
            'statuses': c.BADGE_STATUS_OPTS,
            'checked_in_by_type': c.BADGE_OPTS,
        }
        for label, opts in count_labels.items():
            for val, desc in opts:
                counts[label][desc] = 0
        badge_stocks = c.BADGE_PRICES['stocks']
        for var in c.BADGE_VARS:
            badge_type = getattr(c, var)
            counts['badge_stocks'][c.BADGES[badge_type]] = badge_stocks.get(var.lower(), 'no limit set')
            counts['badge_counts'][c.BADGES[badge_type]] = c.get_badge_count_by_type(badge_type)

        shirt_stocks = c.SHIRT_SIZE_STOCKS
        for shirt_enum_key in c.PREREG_SHIRTS.keys():
            counts['shirt_stocks'][c.PREREG_SHIRTS[shirt_enum_key]] = shirt_stocks.get(shirt_enum_key, 'no limit set')
            counts['shirt_counts'][c.PREREG_SHIRTS[shirt_enum_key]] = c.REDIS_STORE.hget(c.REDIS_PREFIX + 'shirt_counts', shirt_enum_key)

        for a in session.query(Attendee).options(joinedload(Attendee.group)):
            counts['statuses'][a.badge_status_label] += 1
            
            if a.badge_status not in [c.INVALID_GROUP_STATUS, c.INVALID_STATUS, c.IMPORTED_STATUS, c.REFUNDED_STATUS]:
                counts['paid'][a.paid_label] += 1
                counts['ages'][a.age_group_label] += 1
                for val in a.ribbon_ints:
                    counts['ribbons'][c.RIBBONS[val]] += 1
                counts['badges'][a.badge_type_label] += 1
                counts['checked_in']['yes' if a.checked_in else 'no'] += 1
                if a.checked_in:
                    counts['checked_in_by_type'][a.badge_type_label] += 1
                for val in a.interests_ints:
                    counts['interests'][c.INTERESTS[val]] += 1
                if a.paid == c.PAID_BY_GROUP and a.group:
                    counts['groups']['paid' if a.group.amount_paid else 'free'] += 1

                donation_amounts = list(counts['donation_tiers'].keys())
                for index, amount in enumerate(donation_amounts):
                    next_amount = donation_amounts[index + 1] if index + 1 < len(donation_amounts) else six.MAXSIZE
                    if a.amount_extra >= amount and a.amount_extra < next_amount:
                        counts['donation_tiers'][amount] = counts['donation_tiers'][amount] + 1
                if not a.checked_in:
                    is_paid = a.paid == c.HAS_PAID or a.paid == c.PAID_BY_GROUP and a.group and a.group.amount_paid
                    key = 'paid' if is_paid else 'free'
                    counts['noshows'][key] += 1

        return {
            'counts': counts,
        }

    @csv_file
    def checkins_by_hour(self, out, session):
        out.writerow(["Time", "# Checked In"])
        query_result = session.query(
            date_trunc_hour(Attendee.checked_in),
            func.count(date_trunc_hour(Attendee.checked_in))
        ) \
            .filter(Attendee.checked_in.isnot(None)) \
            .group_by(date_trunc_hour(Attendee.checked_in)) \
            .order_by(date_trunc_hour(Attendee.checked_in)) \
            .all()

        for result in query_result:
            hour = localize_datetime(result[0])
            count = result[1]
            out.writerow([hour, count])

    def badges_sold(self, session):
        graph_data_current_year = RegistrationDataOneYear()
        graph_data_current_year.query_current_year(session)

        return {
            'current_registrations': graph_data_current_year.dump_data(),
        }
    
    @csv_file
    def checkins_by_admin_by_hour(self, out, session):
        header = ["Time", "Total Checked In"]
        admins = session.query(Tracking.who).filter(Tracking.action == c.UPDATED,
                                                    Tracking.model == "Attendee",
                                                    Tracking.data.contains("checked_in='None -> datetime")
                                                    ).group_by(Tracking.who).order_by(Tracking.who).distinct().all()
        for admin in admins:
            if not isinstance(admin, six.string_types):
                admin = admin[0] # SQLAlchemy quirk
            
            header.append(f"{admin} # Checked In")

        out.writerow(header)

        query_result = session.query(
            date_trunc_hour(Attendee.checked_in),
            func.count(date_trunc_hour(Attendee.checked_in))
        ) \
            .filter(Attendee.checked_in.isnot(None)) \
            .group_by(date_trunc_hour(Attendee.checked_in)) \
            .order_by(date_trunc_hour(Attendee.checked_in)) \
            .all()
        
        for result in query_result:
            hour = localize_datetime(result[0])
            count = result[1]
            row = [hour, count]
            for admin in admins:
                if not isinstance(admin, six.string_types):
                    admin = admin[0] # SQLAlchemy quirk
                admin_count = session.query(Tracking.which).filter(
                    date_trunc_hour(Tracking.when) == result[0],
                    Tracking.who == admin,
                    Tracking.action == c.UPDATED,
                    Tracking.model == "Attendee",
                    Tracking.data.contains("checked_in='None -> datetime")).group_by(Tracking.which).count()
                row.append(admin_count)
            out.writerow(row)


    if c.MAPS_ENABLED:
        from uszipcode import SearchEngine
        zips_counter = Counter()
        zips = {}
        try:
            center = SearchEngine(db_file_dir="/srv/reggie/data").by_zipcode(20745)
        except Exception as e:
            log.error("Error calling SearchEngine: " + e)

        def map(self):
            return {
                'zip_counts': self.zips_counter,
                'center': self.center,
                'zips': self.zips
            }

        @ajax
        def refresh(self, session, **params):
            zips = {}
            self.zips_counter = Counter()
            attendees = session.query(Attendee).all()
            for person in attendees:
                if person.zip_code:
                    self.zips_counter[person.zip_code] += 1

            for z in self.zips_counter.keys():
                try:
                    found = SearchEngine(db_file_dir="/srv/reggie/data").by_zipcode(int(z))
                except Exception as e:
                    log.error("Error calling SearchEngine: " + e)
                else:
                    if found.zipcode:
                        zips[z] = found

            self.zips = zips
            return True

        @csv_file
        @not_site_mappable
        def radial_zip_data(self, out, session, **params):
            if params.get('radius'):
                try:
                    res = SearchEngine(db_file_dir="/srv/reggie/data").by_coordinates(
                        self.center.lat, self.center.lng, radius=int(params['radius']), returns=None)
                except Exception as e:
                    log.error("Error calling SearchEngine: " + e)
                else:
                    out.writerow(['# of Attendees', 'City', 'State', 'Zipcode', 'Miles from Event', '% of Total Attendees'])
                    if len(res) > 0:
                        keys = self.zips.keys()
                        center_coord = (self.center.lat, self.center.lng)
                        total_count = session.attendees_with_badges().count()
                        for x in res:
                            if x.zipcode in keys:
                                out.writerow([self.zips_counter[x.zipcode], x.city, x.state, x.zipcode,
                                            VincentyDistance((x.lat, x.lng), center_coord).miles,
                                            "%.2f" % float(self.zips_counter[x.zipcode] / total_count * 100)])

        @ajax
        def set_center(self, session, **params):
            if params.get("zip"):
                try:
                    self.center = SearchEngine(db_file_dir="/srv/reggie/data").by_zipcode(int(params["zip"]))
                except Exception as e:
                    log.error("Error calling SearchEngine: " + e)
                else:
                    return "Set to %s, %s - %s" % (self.center.city, self.center.state, self.center.zipcode)
            return False

        @csv_file
        def attendees_by_state(self, out, session):
            # Result of set(map(lambda x: x.state, SearchEngine(db_file_dir="/srv/reggie/data").ses.query(SimpleZipcode))) -- literally all the states uszipcode knows about
            states = ['SD', 'IL', 'WY', 'NV', 'NJ', 'NM', 'UT', 'OR', 'TX', 'NE', 'MS', 'FL', 'VA', 'HI', 'KY', 'MO', 'NY', 'WV', 'DC', 'AR', 'MT', 'MD', 'SC', 'NC', 'KS', 'OH', 'PR', 'CO', 'IN', 'VT', 'LA', 'ND', 'AZ', 'AK', 'AL', 'CT', 'TN', 'PA', 'IA', 'WA', 'ME', 'NH', 'MA', 'ID', 'OK', 'WI', 'GA', 'CA', 'DE', 'MN', 'MI', 'RI']
            total_count = session.attendees_with_badges().count()

            out.writerow(['# of Attendees', 'State', '% of Total Attendees'])

            for state in states:
                try:
                    zip_codes = list(map(lambda x: x.zipcode, SearchEngine(db_file_dir="/srv/reggie/data").by_state(state, returns=None)))
                except Exception as e:
                    log.error("Error calling SearchEngine: " + e)
                else:
                    current_count = session.attendees_with_badges().filter(Attendee.zip_code.in_(zip_codes)).count()
                    if current_count:
                        out.writerow([current_count, state, "%.2f" % float(current_count / total_count * 100)])

