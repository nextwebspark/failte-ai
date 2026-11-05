import { describe, expect, it } from 'vitest';

import { isEmailAddress } from './emailAddress';

describe('isEmailAddress', () => {
    it.each(['owner@bloom.ie', 'a.b+c@mail.example.com'])('accepts %s', (value) => {
        expect(isEmailAddress(value)).toBe(true);
    });

    it.each(['admin@localhost', 'nope', 'a@b', 'a b@bloom.ie', ''])('rejects %s', (value) => {
        expect(isEmailAddress(value)).toBe(false);
    });
});
