# FairShare Chores implementation plan

## Objective

Build a mobile-first PWA for a single shared household of 2–4 roommates. The app fairly assigns recurring chores based on each roommate's completed effort points and sends reminders through WhatsApp and web push notifications.

## Milestone 1 — App foundation

1. Create the responsive PWA shell and installability setup.
2. Define the data model for households, roommates, chores, supplies, swaps, history, and notifications.
3. Implement local identity with a roommate name and device PIN.
4. Build household creation and join-by-code flows.

## Milestone 2 — Chores and fairness

1. Build create, edit, list, and completion flows for chores.
2. Support daily, weekly, monthly, and custom N-hour/day/week/month recurrence.
3. Implement fixed effort points: small = 1, medium = 2, large = 3.
4. Assign each new occurrence to the roommate with the lowest completed-point total; rotate evenly on ties.
5. Keep missed chores overdue until completion and calculate the next due date from the original schedule.
6. Record all completions in full household history.

## Milestone 3 — Coordination and supplies

1. Add targeted swap requests with accept/decline handling.
2. Prevent manual reassignment outside the accepted-swap flow.
3. Add supplies and link a supply to an optional replenishment chore.
4. Mark linked supplies as restocked when their chore is completed.
5. Refresh shared state when the app opens or the user pulls to refresh.

## Milestone 4 — Notifications

1. Request and store web-push permission per roommate/device.
2. Send web-push reminders only to the assigned roommate at each chore's configured time.
3. Integrate a WhatsApp bot to send the same targeted reminders.
4. Verify inbound WhatsApp phone numbers and let a roommate mark only their own assigned chore complete.
5. Keep an in-app simulated SMS/reminder log for a future SMS channel.

## Milestone 5 — AI prompt box

1. Add an AI prompt box on the chores screen.
2. Let it explain fair assignments from completed effort totals.
3. Let it draft new chores from natural-language requests.
4. Let it draft targeted swap requests.
5. Require explicit confirmation before every AI-triggered data change.

## Milestone 6 — Quality and delivery

1. Test the main flows for 2, 3, and 4 roommates.
2. Test assignment ties, late completions, recurrence, swaps, reminders, and WhatsApp authorization.
3. Verify phone-sized layouts, PWA installation, and accessible form controls.
4. Document local setup, environment variables, and WhatsApp configuration.

## Out of scope for this MVP

- Native mobile apps, multiple households, and more than four roommates.
- Email/password accounts, admin roles, manual reassignment, and live in-app updates.
- SMS delivery, WhatsApp swaps, gamification, leaderboards, and fairness dashboards.

