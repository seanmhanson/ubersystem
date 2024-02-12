/**
 * Types defined from shapes in uber/site_sections/tabletop_checkins.py
 */

interface Attendee {
  id: string;
  name: string;
  badge: string;
}

interface Game {
  id: string;
  code: string;
  name: string;
  returned: boolean;
  attendee_id: string;
  attendee: Attendee;
  checked_out: boolean;
}

type Attendees = Array<Attendee>;
type Games = Array<Game>;

export {
  Attendee,
  Attendees,
  Game,
  Games,
}
