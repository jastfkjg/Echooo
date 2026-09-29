"""Run using the CURRENT Attendee release before stopping or migrating it."""
from bots.models import Bot, BotStates

if Bot.objects.exclude(state__in=BotStates.post_meeting_states()).exists():
    raise SystemExit('Attendee has active or scheduled bots. End/cancel them before deploying.')
