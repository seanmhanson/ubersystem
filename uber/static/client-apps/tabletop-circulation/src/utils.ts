import type { Attendee } from "types";

const LETTERS = 'ABCDEFGHJKMNPRSTUVWXYZ';

function *filterWithLimit(array: any[], condition: Function, maxSize: number) {
  if (!maxSize || maxSize > array.length) {
    maxSize = array.length;
  }
  let count = 0;
  let i = 0;
  while ( count< maxSize && i < array.length ) {
    if (condition(array[i])) {
      yield array[i];
      count++;
    }
    i++;
  }
}

const createGuid = () => {
  return [...Array(3)].reduce((guid) => {
    const randLetter = LETTERS[Math.floor(Math.random() * LETTERS.length)];
    const randNumber = Math.floor(Math.random() * 10).toString();
    return `${guid}${randLetter}${randNumber}`
  }, '');
}

const filterAttendees = (attendees: Attendee[], value = '', limit = 8) => {
  const filterMethod = ({ name, badge }: Attendee) => {
    return (
      name.toLowerCase().includes(value) ||
      badge.toLowerCase().includes(value)
    );
  };
  return Array.from(filterWithLimit(attendees, filterMethod, limit));
}

export {
  createGuid,
  filterAttendees
};
