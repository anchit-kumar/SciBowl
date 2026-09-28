"""Track short-lived private replies without persisting interaction credentials."""

import time
from collections import defaultdict

import discord


class PrivateMessages:
    def __init__(self):
        self.entries = defaultdict(list)

    def remember(self, session_id, owner, message):
        self.prune()
        if message is not None and callable(getattr(message, "delete", None)):
            # Leave margin before Discord's 15-minute interaction token expiry.
            self.entries[session_id].append((owner, time.monotonic() + 840, message))

    def prune(self):
        now = time.monotonic()
        for key in list(self.entries):
            live = [entry for entry in self.entries[key] if entry[1] > now]
            if live:
                self.entries[key] = live
            else:
                self.entries.pop(key, None)

    async def clear(self, session_id, owner):
        self.prune()
        removed, failed, retained = 0, 0, []
        for entry in self.entries.pop(session_id, []):
            if entry[0] != owner:
                retained.append(entry)
                continue
            try:
                await entry[2].delete()
                removed += 1
            except discord.NotFound:
                pass
            except discord.HTTPException:
                failed += 1
                retained.append(entry)
        if retained:
            self.entries[session_id].extend(retained)
        return removed, failed
