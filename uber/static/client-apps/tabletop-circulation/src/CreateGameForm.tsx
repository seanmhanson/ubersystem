import React, { useState } from 'react';
import { createGuid, filterAttendees } from './utils';
import type { Attendee } from "types";

interface Props {
  attendees: Attendee[];
  code: string;
  onCreate: any;
}

const AddGameForm = ({
  attendees,
  code,
  onCreate,
}: Props) =>  {
  const [name, setName] = useState('');
  const [owner, setOwner] = useState('');

  const onInputOwner = (val: string) => {
    return filterAttendees(attendees, val.toLowerCase(), 8)
      .map(({ name, badge }) => `${name} (Badge #${badge})`);
  }

  return (
    <table>
      <thead>
        <tr>
          <th />
          <th>Add a Game</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Code:</td>
          <td>
            <input type="text" name="code" value={code} readOnly />
          </td>
        </tr>
        <tr>
          <td>Game:</td>
          <td>
            <input type="text" name="name" autoFocus />
          </td>
        </tr>
        <tr>
          <td>Owner:</td>
          <td>
            <input type="text" name="owner" maxLength={30}/>
          </td>
        </tr>
        <tr>
          <td />
          <td>
            <button onClick={onCreate} disabled={!name || !owner}>Upload</button>
            <a href="/">Cancel</a>
          </td>
        </tr>
      </tbody>
    </table>
  );
}


