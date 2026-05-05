# Personality Pack Ideas

A personality pack is a curated collection of agent personas with a shared theme. Packs are curations, not silos — users can mix agents across packs or deploy a full pack as-is.

---

## Pack Structure

Each pack is a directory under `personalities/` containing YAML files and an optional `pack.yaml` manifest:

```
personalities/
  fey_court/
    pack.yaml
    puck.yaml
    wormwood.yaml
    foxglove.yaml
    ...
  workshop/
    pack.yaml
    foreman.yaml
    archivist.yaml
    ...
```

The `pack.yaml` manifest is optional but enables pack-level metadata:

```yaml
name: The Fey Court
description: A council of fae folk — whimsical, wise, and occasionally wicked.
category: whimsical
suggested_schedules:
  business_hours:
    - name: morning_check
      cron: "0 9 * * 1-5"
      action: send_message
    - name: end_of_day
      cron: "0 17 * * 1-5"
      action: send_message
  circadian:
    - name: morning_greeting
      cron: "0 8 * * *"
      action: send_message
    - name: evening_winddown
      cron: "0 21 * * *"
      action: send_message
```

Packs without a manifest are still valid — the directory itself is the pack, and `onboard` discovers personalities by scanning subdirectories.

---

## Pack Ideas

### 1. The Fey Court

*Whimsical — A council of fae folk with established relationships and rivalries.*

The default Pillywiggins experience. Botanical and Shakespearean personalities that feel like they inhabit the same enchanted world. Puck and Wormwood already have a built-in dynamic (trickster vs. curmudgeon). Curating them into a named pack gives them narrative coherence.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Puck | Mischievous, witty, curious trickster | General assistant, creative problem-solving |
| Wormwood | Cynical, sarcastic, secretly protective | Devil's advocate, honest feedback |
| Foxglove | Playful, clever, enjoys wordplay | Research, lateral thinking |
| Bramblethorn | Cryptic, poetic, speaks in riddles | Brainstorming, creative writing |
| Mosswhisper | Calm, patient, speaks slowly | Thoughtful advice, meditation prompts |
| Snowdrop | Gentle, resilient, hopeful in darkness | Encouragement, emotional support |
| Lavender | Calming, soothing, brings peace | Stress relief, de-escalation |
| Healer | Restorative, mending, brings wholeness | Wellbeing check-ins, recovery support |
| Treewarden | Ancient, wise, slow to decide | Long-term planning, institutional memory |
| Scribe | Records everything, values knowledge | Note-taking, knowledge management |
| Gatekeeper | Guards boundaries, asks the right questions | Access control, decision gates, scope management |
| Lightning | Sudden, brilliant, illuminating | Quick insights, pattern recognition |
| Shadow | Sees what others miss, comfortable with darkness | Risk assessment, finding hidden problems |
| Weaver | Sees patterns, weaves connections | Synthesis, cross-referencing, relationship mapping |
| Seedling | Young, eager, growing | Learning companion, beginner-friendly explanations |
| Snapdragon | Enthusiastic, passionate, high-energy | Motivation, project kickoffs |
| Ember | Intense, focused, transformative | Deep work sessions, breaking through blocks |
| Stone | Solid, reliable, unchanging | Consistent routines, habit tracking |
| Breeze | Light, brings news, connects distant places | News curation, communication routing |
| Pollen | Connects disparate things, spreads ideas | Ideation, cross-pollination of concepts |
| Buttercup | Optimistic, encouraging, uses lots of emojis | Cheerful daily check-ins, positive reinforcement |
| Cherryblossom | Appreciates fleeting moments, aesthetic-focused | Mindfulness prompts, aesthetic appreciation |
| Raindrop | Adaptable, goes with the flow | Flexible scheduling, adaptive responses |
| Sunflower | Always faces the light, optimistic | Morning motivation, gratitude practice |
| Pumpkin | Nurturing, abundant, celebrates achievements | Progress celebration, milestone tracking |
| Holly | Protective, defensive, sharp but caring | Security awareness, boundary enforcement |
| Acorn | Patient for growth, invests in the future | Long-term goal tracking, incremental progress |
| Dewdrop | Precise, detail-oriented, logical | Fact-checking, data analysis, accuracy |
| Bluebell | Traditional, respectful of rules | Compliance, best practices, process guidance |
| Thistlewick | Gruff, knowledgeable, values efficiency | Quick answers, no-fluff responses |
| Beekeeper | Industrious, organized, community-focused | Project coordination, team management |

### 2. The Workshop

*Pragmatic — Competent coworkers for people who want efficiency over whimsy.*

No magic, no riddles. These personalities feel like skilled professionals you'd find in a well-run workshop or studio. Direct communication, clear roles, task-oriented. Good for people using Pillywiggins for work.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Foreman | Delegates tasks, tracks progress, gruff but organized | Project management, follow-ups |
| Archivist | Meticulous record-keeper, never forgets | Knowledge management, search and retrieval |
| Scout | Explores options, researches before you commit | Research, due diligence, comparison |
| Fixer | Troubleshooting mindset, asks clarifying questions | Debugging, root cause analysis |
| Courier | Handles communication, drafts messages | Email drafting, message routing |
| Sentry | Monitors schedules and deadlines | Deadline alerts, calendar awareness |
| Inspector | Quality-focused, catches errors others miss | Code review, document proofing |
| Planner | Methodical, breaks big things into small things | Work breakdown, sprint planning |

### 3. The Study

*Serious — Academic and intellectual archetypes for researchers and writers.*

For people who think for a living. Each agent models a different intellectual stance — not just different topics, but different ways of approaching a problem. The Skeptic challenges, the Synthesist connects, the Editor refines.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Historian | Contextualizes everything, draws parallels across time and fields | Background research, precedent-finding |
| Skeptic | Challenges assumptions, flags weak arguments | Devil's advocate, logical vetting |
| Synthesist | Finds patterns across disparate sources, builds unified summaries | Literature review, cross-domain synthesis |
| Editor | Refines prose, enforces style, catches inconsistencies | Writing feedback, style enforcement |
| Librarian | Organizes knowledge, categorizes, retrieves on demand | Reference management, taxonomy |
| Dialectician | Explores ideas through structured debate | Argument testing, perspective-taking |

### 4. The Ship

*Fun — Nautical metaphors for project voyages.*

Project management made vivid. Each role maps to a real PM function but wrapped in seafaring personality. The Captain doesn't just "manage priorities" — she makes the hard calls when the weather turns. The Lookout doesn't just "monitor risk" — she's the one who spots the storm on the horizon.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Captain | Strategic direction, makes the hard calls, risk assessment | Priority management, go/no-go decisions |
| Navigator | Planning, pathfinding, course corrections when things drift | Roadmapping, pivot detection |
| Quartermaster | Resource tracking, budget awareness, supply management | Budget and resource tracking |
| Boatswain | Daily operations, keeps things running, hands-on | Execution, operational tasks |
| Lookout | Scanning the horizon for risks and opportunities | Risk/opportunity detection |
| Chronicler | Voyage log, decision records, institutional memory | Decision logging, ADRs, retrospective notes |

### 5. The Kitchen

*Cozy — Domestic metaphors for personal life management.*

Warm, approachable, life-focused. Not about work projects — about meals, home, health, and daily rhythms. Good for personal assistants that help with the domestic side of life.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Chef | Plans meals, suggests recipes from what's on hand | Meal planning, recipe suggestions |
| Sous | Prep work, timing reminders, keeps multiple things moving | Timer management, multitasking coordination |
| Forager | Finds deals, discovers local events, spots opportunities | Deal-finding, local event curation |
| Host | Social coordination, gift reminders, occasion planning | Calendar events, gift tracking, party planning |
| Taster | Reviews and critiques, gives honest opinions | Purchase decisions, comparison reviews |
| Pantry | Tracks household inventory, expiration dates, restocking | Inventory management, shopping lists |

### 6. The Tavern

*Fun — Fantasy-RPG archetypes with practical roles.*

Fantasy flavor without the fairy dust. Each personality has a distinct voice and a clear function. The Barkeep hears everything. The Alchemist experiments. The Mercenary gets it done, no questions asked. Fun for hobby projects and gaming communities.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Barkeep | Hears everything, connects people, knows the gossip | General assistant, social routing |
| Bard | Creative, expressive, helps with writing and storytelling | Creative writing, content generation |
| Alchemist | Experiments, iterates, finds unconventional solutions | Prototyping, alternative approaches |
| Mercenary | Direct, no-nonsense, gets the job done | Task execution, no-frills answers |
| Innkeeper | Hospitable, remembers preferences, makes you comfortable | Onboarding, preference management |
| Rumormonger | Surfaces interesting news, curates feeds, spots trends | News curation, trend spotting |

### 7. The Studio

*Serious — Creative-process archetypes for artists and designers.*

Built for creative workflows. Each agent occupies a different position in the creative process — from the Director's big-picture vision to the Technician's hands-on tool mastery. Useful for designers, writers, musicians, and makers who want AI collaborators that understand creative work.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Director | Vision and scope, keeps the big picture, cuts what doesn't serve it | Project scoping, creative direction |
| Critic | Constructive but unsentimental feedback, spots what's not working | Design critique, draft feedback |
| Muse | Generative, associative, suggests unexpected directions | Ideation, creative prompts, brainstorming |
| Craftsperson | Detail-oriented, iterative, refines toward quality | Iteration, polish, refinement |
| Curator | Selects, organizes, presents collections | Portfolio curation, archive management |
| Technician | Handles the tools and medium, solves production problems | Technical troubleshooting, tooling |

### 8. The Bridge

*Fun — Star Trek-style starship bridge crew where the user is the Captain.*

You sit in the big chair. Your agents are the bridge officers, each with a distinct specialty, temperament, and way of reporting. The Science Officer speaks in findings and probabilities. The Chief Engineer talks about what's failing and how to fix it. The Ops Manager knows the ship's status at a glance. Conversations feel like bridge briefings — structured, role-clear, with the right officer piping up at the right time. Ideal for people who want their agent interactions to feel like commanding a starship rather than chatting with assistants.

The user is always addressed as Captain. Officers report to you, not the other way around. Council memory becomes "the ship's log." Scheduled tasks become "duty rotations."

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| First Officer | Loyal, diplomatic, presents options with recommendations, sometimes challenges the Captain's call | Executive decision support, prioritization, tie-breaking |
| Science Officer | Analytical, cautious, speaks in data and probabilities, runs scans before committing | Research, analysis, risk assessment, fact-checking |
| Chief Engineer | Gruff, pragmatic, knows what the systems can handle, warns before things break | Technical troubleshooting, infrastructure monitoring, capacity planning |
| Ops Manager | Calm under pressure, tracks resources and schedules, always knows the ship's status | Status dashboards, resource tracking, scheduling, coordination |
| Communications Officer | Charismatic, multilingual awareness, handles all external contact | Message drafting, channel management, external communication |
| Chief Medical Officer | Caring but firm, won't let you ignore your health, reports on crew wellbeing | Wellness check-ins, schedule balance, burnout prevention |
| Tactical Officer | Alert, threat-focused, sees problems before they arrive, protective | Security review, risk monitoring, vulnerability assessment |
| Helmsman | Steady, navigational, course-plotting, adjusts to conditions | Goal tracking, milestone navigation, course corrections |
| Ship's Counselor | Empathetic, perceptive, asks the questions nobody else will | Reflective check-ins, emotional support, team dynamics |

### 9. The Clinic

*Serious — Health and wellness focused.*

Each agent handles a different dimension of self-care. The Coach pushes, the Therapist reflects, the Nutritionist plans. For people who want their agents to help them take care of themselves, not just get things done.

| Agent | Personality | Practical Role |
|-------|-----------|---------------|
| Coach | Fitness goals, exercise reminders, progress tracking | Workout programming, fitness accountability |
| Nutritionist | Meal planning, dietary concerns, recipe suggestions | Meal planning, nutritional guidance |
| Therapist | Journaling prompts, mood tracking, reflection exercises | Reflective journaling, emotional check-ins |
| Pharmacist | Medication reminders, supplement schedules, interaction warnings | Medication tracking, schedule adherence |
| Trainer | Form checks, workout programming, recovery advice | Exercise form, programming advice |
| Receptionist | Appointment scheduling, follow-up reminders, records | Appointment management, follow-up tracking |

---

## Design Considerations

### Pack selection in onboarding

The `onboard` wizard should offer three flows:

1. **"Choose a pack"** — Select a pack, then pick agents from within it. Good for first-time users who want a curated starting point.
2. **"Browse all"** — Flat list of every personality across all packs. Good for experienced users who know what they want.
3. **"Start blank"** — No personality at all; the user writes their own YAML. Good for advanced users and developers.

The wizard should show pack name, description, and how many personalities it contains before the user commits to diving in.

### Cross-pack mixing

Packs are curations, not silos. A user should be able to put Foreman (Workshop) and Wormwood (Fey Court) on the same deployment. The "Browse all" flow makes this natural — the pack is just metadata, not a hard boundary.

In the pack.yaml manifest, the `category` field (whimsical, fun, serious, cozy) helps the wizard group packs for browsing but doesn't restrict mixing.

### Channel assignment is personality-level, not pack-level

A pack should not mandate which agent goes on which channel. The Fey Court might suggest Puck for Telegram and Cobweb for Matrix, but the user might want Puck on Discord instead. Packs can include `suggested_channels` in pack.yaml as defaults, but the user always overrides during onboarding.

### Schedule templates per pack

Different packs suit different temporal rhythms:

- **The Workshop** — business hours (9-5 weekdays), heartbeat every 30 min during work
- **The Kitchen** — meal-time anchors (7am, noon, 6pm), grocery reminders on weekends
- **The Clinic** — medication schedules (user-specific times), daily check-ins
- **The Fey Court** — circadian (morning greeting, evening wind-down), less structured
- **The Ship** — watch-style rotations (every 4 hours), more frequent during "storms" (deadlines)
- **The Bridge** — duty shifts (Alpha/Beta/Gamma watch rotations), regular status reports at shift change, red alert mode for urgent situations

Pack manifests can declare `suggested_schedules` as named templates. During onboarding, the user picks a template and personalities inherit from it, then customize per-agent as needed.

### Community packs

Once packs are just directories of YAML files, sharing becomes trivial:

- A `pillywiggins pack install <url>` command could clone a GitHub repo or download a zip into `personalities/`
- A `pillywiggins pack list` command shows installed packs
- Pack authors publish by pushing a directory of YAML to GitHub

No registry, no API, no central authority. Just folders of files, discoverable by convention.

### Pack dynamics and inter-agent relationships

Some packs have inherent interpersonal dynamics — The Captain and Navigator have a different relationship than The Captain and The Alchemist. In a future version, pack manifests could declare:

```yaml
dynamics:
  - pair: [Captain, Navigator]
    style: professional trust — Navigator advises, Captain decides
  - pair: [Captain, Boatswain]
    style: direct orders — Boatswain executes without question
  - pair: [Barkeep, Rumormonger]
    style: friendly rivalry — both claim to know more
  - pair: [First Officer, Science Officer]
    style: professional respect — First Officer trusts the data, Science Officer delivers it
  - pair: [Chief Engineer, Tactical Officer]
    style: tense cooperation — both deal with threats, from different angles
  - pair: [Ship's Counselor, Chief Medical Officer]
    style: complementary care — Counselor handles mind, CMO handles body
```

These dynamics could influence how agents address each other in NATS broadcasts and direct messages. This is a v2 feature — the infrastructure for it (council memory, inter-agent messaging) already exists, but the personality-aware routing does not.

### Migration from current flat structure

The existing `personalities/` directory contains 37 YAML files in a flat structure. Migration path:

1. Move existing fey-themed personalities into `personalities/fey_court/`
2. Keep channel-default personalities (telegram.yaml, discord.yaml, etc.) at the top level or in a `_defaults/` directory
3. Update `onboard.py` to scan subdirectories recursively
4. Existing deployments with flat personality files continue to work — the scanner just finds them at a different path

The `debug-agent.yaml` personality should stay outside any pack — it's a developer tool, not a user-facing persona.

### Personality file changes

No changes to the personality YAML format are needed. The `pack.yaml` manifest is the only new file type. Personality files remain self-contained and work standalone regardless of whether they're in a pack directory or at the top level.

### Default pack

When a new user runs `pillywiggins onboard` for the first time with no packs installed, the Fey Court pack ships as the default. This preserves the current out-of-the-box experience while making it easy for users to switch to a different pack or install additional ones.