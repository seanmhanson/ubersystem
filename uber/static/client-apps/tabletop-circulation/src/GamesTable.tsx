import React from 'react';
import type { Games } from "./types";

interface Props {
  games: Games;
}

const GamesTable = ({
  games,
}: Props) => {
  return (
    <table>
      <thead>
        <tr>
          <th>Game</th>
          <th>Status</th>
          <th>Attendee</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        {games.map((game) => (
          <tr key={game.id}>
            <td>{game.name}</td>
            <td>{game.checked_out?.when ? 'Checked Out' : 'Available'}</td>
            <td>
              {/** Replace with Attendee link from directive */}
              {game.checked_out?.attendee?.name}
              {game.checked_out?.when && `at ${game.checked_out.when}`}
            </td>
            <td>
              {game.checked_out?.when
                ? <button>Return</button>
                : <button>Check Out</button>
              }
              <button>History</button> {/** href="checkout_history?id={{ game.id }} */}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}


/* <td><input autofocus type="text" size="30" ng-model="game" typeahead-editable="false" typeahead="g as ('[' + g.code + '] ' + g.name) for g in games | filter:{returned: false} | filter:nameOrCode($viewValue) | limitTo:8" /></td>
<input autofocus type="text" size="30" ng-model="attendee" typeahead-editable="false" typeahead="a as (a.name + ' (Badge #' + a.badge + ')') for a in attendees | filter:nameOrBadge($viewValue) | limitTo:8" /> */

export default GamesTable;