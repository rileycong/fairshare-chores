# FairShare Chores — MVP Product Requirements

## 1. Product summary

FairShare Chores is a mobile-first, installable web app for **one shared household of 2–4 roommates**. It assigns recurring household chores fairly by balancing each roommate's **completed effort points**, makes assignments and overdue work visible, and sends reminders through WhatsApp and web push notifications.

The app is designed for roommates rather than families or couples. It prioritizes clear coordination and a fair rotation over gamification or complex household administration.

## 2. Problem

Roommates often share chores unevenly because it is difficult to remember who has done what, track recurring tasks, and coordinate schedule changes. A static roster is not enough: cleaning a bathroom should count more than taking out rubbish.

## 3. MVP goals

- Keep a shared, visible list of active, completed, and overdue chores.
- Assign the next recurring chore to the roommate with the lowest completed effort total.
- Support swaps that require acceptance by a specific roommate.
- Remind the assigned roommate at a configured time through WhatsApp and browser push notifications.
- Let a roommate complete their own assigned chore from either the app or WhatsApp.
- Let the household manage chores and supplies without an administrator role.
- Use AI to suggest and explain fair assignments and to interpret natural-language requests safely.

## 4. Users and identity

### Household

- A household has 2–4 roommates.
- One roommate creates the household and receives a shared join code.
- Other roommates join with that code.
- The MVP supports **one household per device/profile**; switching households is out of scope.

### Roommate identity

- No email/password accounts.
- Each roommate creates a display name and a private PIN on their device.
- The device retains the identity for later visits.
- Each roommate must provide a WhatsApp phone number, which links their WhatsApp replies and reminders to their profile.
- All roommates have equal edit permissions. There is no household manager after creation.

## 5. Core data

### Roommate

- Display name
- Local device PIN
- WhatsApp phone number
- Completed effort-point total
- Tie-break position in the household rotation

### Chore

- Name
- Optional notes/instructions
- Effort size: small, medium, or large
- Fixed effort points: small = 1, medium = 2, large = 3
- Recurrence: preset daily, weekly, or monthly; or custom every **N** hours, days, weeks, or months
- Reminder time for this chore
- Current assignee
- Due date/time
- Status: assigned, swap requested, overdue, or completed
- Optional linked supply item

### Supply

- Name
- Restocked/not-restocked status
- Optional linked chore, such as “buy toilet paper”

### History record

- Chore and assignee
- Effort points
- Due date/time
- Completion date/time
- Whether the assignment was swapped

## 6. Core flows

### Create or join a household

1. A roommate creates a household, enters their name, PIN, and WhatsApp number, then receives a join code.
2. Another roommate enters the code, name, PIN, and WhatsApp number.
3. The joined household is saved locally on the device.

### Create a chore

1. Any roommate creates a chore, selects its effort size and recurrence, and optionally adds notes and a linked supply.
2. They set a reminder time for that specific chore.
3. The app assigns the first occurrence to the roommate with the lowest completed-point total.
4. If totals are tied, the app uses an even rotating tie-breaker.

### Complete a chore

1. Only the current assignee can mark their chore as done in the app.
2. Completion adds the chore's fixed effort points to that roommate's completed total and saves a permanent history record.
3. If a supply is linked, the supply is marked as restocked.
4. The next occurrence is scheduled from the chore's **original schedule**, not from the late completion time.
5. The next occurrence is assigned to the eligible roommate with the lowest completed-point total. Ties rotate evenly.

### Handle overdue chores

- A chore remains overdue until the assigned roommate completes it.
- It is visible to the entire household in the app.
- The household does not receive an overdue WhatsApp alert; only the assignee receives the normal per-chore reminders.
- Overdue chores do not automatically move to another roommate.

### Swap a chore

1. The assignee selects a specific roommate and requests a swap.
2. That roommate accepts or declines.
3. On acceptance, the chore's assignee changes and the history records the swap.
4. Manual reassignment outside this accepted-swap flow is not allowed.

## 7. Notifications and WhatsApp

### Web push

- Send a push notification only to the assigned roommate.
- Send it at the chore's configured reminder time.

### WhatsApp bot

- Use a real WhatsApp integration in the MVP.
- Send reminders only to the assigned roommate at the chore's configured time.
- A roommate can reply to the bot to mark **their own** assigned chore as done.
- The backend verifies the sender's phone number before applying the completion.
- WhatsApp does not support swap requests in this MVP.

### SMS

- SMS is not sent in the MVP.

## 8. AI assistant

The app exposes one prompt box on the chores screen. The AI can:

- Suggest the next fair assignment using completed effort points.
- Explain why an assignment is fair in plain language.
- Interpret requests such as “swap my chores this week.”
- Create chores from requests such as “add vacuuming every two weeks.”

Any AI action that changes data, including creating a chore or proposing a swap, must show a confirmation before the app saves or sends anything.

## 9. Main screens

1. **Welcome / household setup** — create a household or join with a code.
2. **Chores** — current assignments, due dates, status, notes, the AI prompt box, and pull-to-refresh.
3. **Chore editor** — create/edit name, notes, effort, recurrence, reminder time, and linked supply.
4. **Swap request** — choose a specific roommate; recipient accepts or declines.
5. **Supplies** — restock status and linked supply chores.
6. **History** — full completed-chore history for the household.
7. **Settings** — roommate details, WhatsApp number, web-push permission, and household join code.

The app does not require live synchronization while open. Roommates see changes when they reopen the app or use pull-to-refresh.

## 10. Explicitly out of scope

- Native iOS/Android apps (this is a mobile-friendly PWA).
- Multiple households per roommate/device.
- More than four roommates.
- Email/password accounts.
- Household roles or an administrator after creation.
- Manual reassignment.
- SMS delivery.
- WhatsApp swap handling.
- A fairness dashboard, leaderboard, badges, streaks, or other gamification.
- Automatic reassignment of overdue chores.
- Real-time in-app synchronization.
- Separate effort-point scales per household.

## 11. Acceptance criteria

- A household can be created and joined by up to four roommates using a shared code.
- A roommate can create a recurring chore with an effort size and a per-chore reminder time.
- The system assigns new occurrences by lowest completed effort total and rotates tied roommates fairly.
- Only the assignee can complete an assigned chore in the app; the WhatsApp bot can only complete a chore for its matched phone number.
- Completing a chore records history, updates point totals, schedules the next occurrence from the original cadence, and updates any linked supply to restocked.
- A swap requires approval from the specifically selected roommate.
- Overdue chores remain visible until completed.
- The AI can create a chore, suggest/explain an assignment, and propose a swap, but each action requires explicit user confirmation.
- The app can be installed as a PWA and is usable on a phone-sized screen.
