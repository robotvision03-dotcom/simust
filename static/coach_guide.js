/**
 * SIMUST Coach Guide — operator Docs tab.
 * Plain React.createElement (no JSX). Exposes window.CoachGuidePanel.
 */
(function (global) {
  "use strict";

  var h = React.createElement;
  var useState = React.useState;
  var useEffect = React.useEffect;
  var useRef = React.useRef;

  function ms(sec) {
    return String(sec);
  }

  function img(src, alt) {
    return { src: src, alt: alt || "" };
  }

  var ENTRY_TIMING = [
    { set: "C1 / T1", on: "3.0 s", gap: "1.0 s" },
    { set: "C2 / T2", on: "2.7 s", gap: "0.9 s" },
    { set: "C3 / T3", on: "2.4 s", gap: "0.8 s" },
    { set: "C4 / T4", on: "2.2 s", gap: "0.7 s" },
    { set: "C5 / T5", on: "2.0 s", gap: "0.7 s" },
  ];

  var ELITE_TIMING = [
    { set: "T1", on: "4.5 s", gap: "0.5 s" },
    { set: "T2", on: "4.1 s", gap: "0.5 s" },
    { set: "T3", on: "3.6 s", gap: "0.5 s" },
    { set: "T4", on: "3.3 s", gap: "0.5 s" },
    { set: "T5", on: "3.0 s", gap: "0.5 s" },
  ];

  var NAV = [
    { group: "Start here" },
    { id: "welcome", label: "Welcome" },
    { id: "basics", label: "How a session works" },
    { id: "field-goals", label: "Fields, goals & HIP" },
    { id: "level-map", label: "Level map" },
    { group: "Bands" },
    { id: "foundation", label: "Foundation" },
    { id: "entry", label: "Entry" },
    { id: "activated", label: "Activated" },
    { id: "hp", label: "High Performance" },
    { id: "elite", label: "Elite" },
    { id: "world", label: "World Class" },
    { group: "Coach tools" },
    { id: "unlock", label: "Unlock & level-up" },
    { id: "timing", label: "Timing tables" },
    { id: "manual", label: "Manual Coach" },
    { id: "tips", label: "Quick tips" },
  ];

  function pageWelcome() {
    return {
      kicker: "Coach handbook",
      title: "Welcome to SIMUST",
      lead:
        "This guide explains every training band in plain language — what the athlete sees, what they must do, how long each cue stays on, and how they unlock the next set.",
      blocks: [
        {
          type: "callout",
          kind: "tip",
          html:
            "<strong>Who this is for.</strong> Coaches and operators who run Field A / Field B sessions. You do not need to know the software internals — only the game rules and timings.",
        },
        {
          type: "h2",
          text: "What SIMUST is",
        },
        {
          type: "p",
          text:
            "SIMUST is a dual-field cognitive football trainer. Players watch screens around the pitch, decide the correct target, and kick a real ball into a goal mouth. The system scores Correct, Wrong, Late, or Miss, then shows short processing and results rings.",
        },
        {
          type: "h2",
          text: "The six bands (easy → hard)",
        },
        {
          type: "map",
          items: [
            { em: "L00", text: "Foundation" },
            { em: "L01", text: "Entry" },
            { em: "L02", text: "Activated" },
            { em: "L03", text: "High Performance" },
            { em: "L04", text: "Elite" },
            { em: "L05", text: "World Class" },
          ],
        },
        {
          type: "p",
          text:
            "Inside most bands you will see Components such as Players, Numbers, Divergent, and Sum. The wall label looks like C1.T3 — Component 1, Test set 3.",
        },
        {
          type: "grid",
          cards: [
            {
              title: "Pass image",
              text: "Kick toward this teammate / pass still.",
              image: img("/static/players/Entry/pass.png", "Entry pass"),
            },
            {
              title: "Opponent still",
              text: "Distractor — do not kick here.",
              image: img(
                "/static/players/Entry/Opponent-PL-01-B.png",
                "Opponent"
              ),
            },
            {
              title: "Elite pass1",
              text: "Elite Players goal image.",
              image: img("/static/players/Elite/pass1.png", "Elite pass1"),
            },
          ],
        },
      ],
    };
  }

  function pageBasics() {
    return {
      kicker: "Session flow",
      title: "How a session works",
      lead:
        "Every set follows the same rhythm. Once you know this loop, every band is easier to coach.",
      blocks: [
        {
          type: "steps",
          items: [
            "Select player(s), band, and Component (for example Entry → Players C1.T1).",
            "Start the smart player. An opening card shows the band name and Component.",
            "A cue appears on the wall screens (player image, number, letter, or sum).",
            "Athlete decides and kicks. The ball must enter the painted Goal Area and hold in the HIP zone.",
            "System shows Correct / Wrong / Late / Miss, then a short processing animation (~4 s) and results rings (~4 s).",
            "Next action appears after the gap time. After the last test, finals may unlock the next set.",
          ],
        },
        {
          type: "h2",
          text: "Words you will hear",
        },
        {
          type: "table",
          headers: ["Term", "Meaning"],
          rows: [
            ["On time", "How long the cue stays visible before it clears."],
            ["Gap", "Short dark pause before the next cue."],
            ["Test / set", "A block of actions (often 5 tests × 6–12 actions)."],
            ["Component (C#)", "Content family: Players, Numbers, Divergent, Sum."],
            ["finish_balls", "Live mode — wait for a real ball goal, not a timer alone."],
            ["Field A / B", "Left and right halves. Elite/World Class often use both as one 12-screen field."],
          ],
        },
        {
          type: "callout",
          kind: "",
          html:
            "<strong>Scoring tip.</strong> Accuracy (ACC) is Correct vs attempts. Action Efficiency (AE) also cares about early arrivals. Unlock after Entry uses AE ≥ 70% (Foundation uses 65%).",
        },
      ],
    };
  }

  function pageFieldGoals() {
    return {
      kicker: "Hardware rules",
      title: "Fields, Goal Area & HIP",
      lead:
        "A Correct pass is not “near the goal”. The ball must enter the Goal Area mesh and change direction there (screen bounce / return) — same rule on Entry through Elite. The red HIP zone is not used for Correct.",
      blocks: [
        {
          type: "h2",
          text: "Screens",
        },
        {
          type: "p",
          text:
            "Each field has mouths A1–A6 (or B1–B6). Foundation and Entry often use one field at a time. Elite Players and Elite/World Class number games treat A+B as twelve screens together.",
        },
        {
          type: "h2",
          text: "Goal Area finish (live pass)",
        },
        {
          type: "steps",
          items: [
            "Green Goal Area lights on the target mouth when the cue is live.",
            "Ball must travel into that painted Goal Area (not only cross a line).",
            "While inside the Goal Area, heading must change more than 15° (hit screen and return).",
            "If the ball leaves the Goal Area without that turn → Wrong / try again on the same screen.",
            "If the turn is good → Correct and the next cue can advance immediately.",
          ],
        },
        {
          type: "callout",
          kind: "warn",
          html:
            "<strong>Coach note.</strong> If Correct feels “late” or never comes, check Goal Area Calibration in Settings (staff). Do not tell the athlete to kick softer until the mesh is verified.",
        },
        {
          type: "h2",
          text: "Independent vs combined",
        },
        {
          type: "table",
          headers: ["Mode", "What coaches see"],
          rows: [
            ["Independent A/B", "Each half can run its own band (dual booking). Stop one field without stopping the other."],
            ["Combined (Elite/WC)", "One decision across 12 screens. Both walls light as one puzzle."],
          ],
        },
      ],
    };
  }

  function pageLevelMap() {
    return {
      kicker: "Overview",
      title: "Level map",
      lead:
        "Use this page as a menu of everything athletes can unlock. Operator folders may say S0.T1 while the wall shows C1.T1 — that is normal.",
      blocks: [
        {
          type: "table",
          headers: ["Band", "Components (wall)", "Internal ids", "Fields"],
          rows: [
            ["Foundation", "SF-30N → SF-180N, math, cognitive, extras", "L00 playlists", "Usually one field"],
            ["Entry", "Players C1 · Numbers C2", "S0 · S1", "A and/or B"],
            ["Activated", "Players C1 · Numbers C2 · Divergent C3", "S0 · S1 · S2", "A and/or B"],
            ["High Performance", "Players C1 · Numbers C2 · Divergent C3 · Sum C4", "S0–S3", "A and/or B"],
            ["Elite", "Players C1 · Numbers C2 · Divergent C3 · Sum C4", "S0–S3", "Combined 12 screens"],
            ["World Class", "Numbers C1 · Divergent C2 · Sum C3", "S1–S3", "Combined 12 screens"],
          ],
        },
        {
          type: "callout",
          kind: "tip",
          html:
            "<strong>Label rule.</strong> Entry → Elite shift internal S0 to wall <em>C1</em> (add one). World Class keeps S1 as wall <em>C1</em>.",
        },
        {
          type: "h2",
          text: "Typical sizes",
        },
        {
          type: "table",
          headers: ["Family", "Tests", "Actions / test", "Cue style"],
          rows: [
            ["Entry / Activated Players", "5", "10", "Player stills"],
            ["Entry / Activated Numbers", "5", "6", "Digits, lowest first"],
            ["HP / Elite / WC Numbers & Divergent", "5", "12 (Elite/WC) or 6 (HP)", "Digits / odd-one-out"],
            ["Sum (HP / Elite / WC)", "5", "6 or 12", "Encode reference, then pair that sums"],
          ],
        },
      ],
    };
  }

  function pageFoundation() {
    return {
      kicker: "L00",
      title: "Foundation",
      lead:
        "Foundation builds basic pass timing, screen awareness, and simple decisions before Entry Players.",
      blocks: [
        {
          type: "h2",
          text: "SF scripts (degree spacing)",
        },
        {
          type: "p",
          text:
            "SF-30N, SF-60N, SF-110N, SF-180N place pass cues with increasing spacing difficulty. On time is about 3.0 s with a short gap (~0.5 s). Athletes pass to the lit screen.",
        },
        {
          type: "table",
          headers: ["Playlist", "Idea for coaches"],
          rows: [
            ["SF-30N", "Closest / easiest spacing — first unlock chain."],
            ["SF-60N", "Wider jumps between screens."],
            ["SF-110N", "Harder travel patterns."],
            ["SF-180N", "Largest spacing before Entry."],
          ],
        },
        {
          type: "h2",
          text: "Other Foundation modes",
        },
        {
          type: "table",
          headers: ["Mode", "What to tell the athlete"],
          rows: [
            ["Math (sum / sub / × / ÷)", "Solve the shown problem; kick the answer screen."],
            ["Cognitive encode", "Watch a short encode, then answer on the field screens."],
            ["Omid / number clear", "Numbers stay up longer (~8 s); faster clean goals score better efficiency."],
            ["Rabbit / extras", "Follow the moving light or special script — kick the active screen."],
          ],
        },
        {
          type: "callout",
          kind: "",
          html:
            "<strong>Unlock.</strong> Foundation uses AE ≥ <strong>65%</strong> to open the next SF / playlist. Passing the last Foundation set opens Entry Players C1.T1.",
        },
      ],
    };
  }

  function pageEntry() {
    return {
      kicker: "L01 · Entry",
      title: "Entry band",
      lead:
        "Entry teaches “find the pass among stills” and then “always clear the lowest number”. Timing starts gentle and gets 10% faster each Component set.",
      blocks: [
        {
          type: "h2",
          text: "Players — wall C1 (internal S0)",
        },
        {
          type: "p",
          text:
            "5 tests × 10 actions. Kick only the pass image. Other screens show opponents / teammates as distractors. Placement reshuffles every action.",
        },
        {
          type: "table",
          headers: ["Set", "Images on field", "Coach focus"],
          rows: [
            ["C1.T1–T2", "3 stills on 3 of 6 screens", "Pass + 2 opponents; opponents not adjacent."],
            ["C1.T3–T5", "5 stills on 5 of 6 screens", "More clutter — same rule: only the pass."],
          ],
        },
        {
          type: "grid",
          cards: [
            {
              title: "Pass",
              text: "Correct target",
              image: img("/static/players/Entry/pass.png", "pass"),
            },
            {
              title: "Teammate",
              text: "Friendly distractor",
              image: img(
                "/static/players/Entry/Teammate-PL-01-B.png",
                "teammate"
              ),
            },
            {
              title: "Opponent",
              text: "Do not pass here",
              image: img(
                "/static/players/Entry/Opponent-PL-02-B.png",
                "opponent"
              ),
            },
          ],
        },
        {
          type: "h2",
          text: "Numbers — wall C2 (internal S1)",
        },
        {
          type: "p",
          text:
            "5 tests × 6 actions. Six numbers appear. Always pass the lowest remaining number; that screen clears; repeat until all are gone. Field B can mirror the same puzzle.",
        },
        {
          type: "table",
          headers: ["Test", "Number layout idea"],
          rows: [
            ["T1", "Digit N on screen N (1→6)."],
            ["T2", "Reversed: digit N on screen 7−N."],
            ["T3–T5", "Digits 1–6 shuffled onto the six screens."],
          ],
        },
        {
          type: "h2",
          text: "Entry timing (Players & Numbers)",
        },
        {
          type: "table",
          headers: ["Set", "On (cue)", "Gap"],
          rows: ENTRY_TIMING.map(function (r) {
            return [r.set, r.on, r.gap];
          }),
        },
        {
          type: "callout",
          kind: "tip",
          html:
            "<strong>Floor.</strong> On time never goes below ~1.8 s; gap never below ~0.5 s.",
        },
      ],
    };
  }

  function pageActivated() {
    return {
      kicker: "L02 · Activated",
      title: "Activated band",
      lead:
        "Activated adds side goals and odd-one-out thinking while keeping Entry-style timing.",
      blocks: [
        {
          type: "h2",
          text: "Players — C1",
        },
        {
          type: "p",
          text:
            "5 × 10 actions. Pass among teammate + opponents. Later sets add pass-left / pass-right side targets.",
        },
        {
          type: "table",
          headers: ["Set", "Scenario"],
          rows: [
            ["C1.T1–T2", "Center pass (pass / pass3) + teammate + 3 opponents."],
            ["C1.T3–T5", "Mix of center passes and pass-left / pass-right side goals."],
          ],
        },
        {
          type: "grid",
          cards: [
            {
              title: "Pass",
              text: "Center target",
              image: img("/static/players/Activated/pass.png", "pass"),
            },
            {
              title: "Pass left",
              text: "Side goal L",
              image: img("/static/players/Activated/pass-left.png", "pass left"),
            },
            {
              title: "Pass right",
              text: "Side goal R",
              image: img(
                "/static/players/Activated/pass-right.png",
                "pass right"
              ),
            },
            {
              title: "Opponent",
              text: "Distractor",
              image: img(
                "/static/players/Activated/Opponent-PL-04-B.png",
                "opponent"
              ),
            },
          ],
        },
        {
          type: "h2",
          text: "Numbers — C2",
        },
        {
          type: "p",
          text:
            "Same “lowest number first” game as Entry, but with Activated number sheets (for example T1: 10, 30, 50, 60, 40, 20). Timing matches Entry decay.",
        },
        {
          type: "h2",
          text: "Divergent — C3",
        },
        {
          type: "p",
          text:
            "Odd-one-out on each field: five screens match, one is different. Kick the different screen. Early tests use 1-digit numbers; later tests use 2–3 digits or similar letter triples (LOL vs TOL).",
        },
        {
          type: "callout",
          kind: "",
          html:
            "<strong>Timing.</strong> Same table as Entry (3.0 s → ~2.0 s). Completing Divergent C3.T5 opens High Performance Players C1.T1.",
        },
      ],
    };
  }

  function pageHp() {
    return {
      kicker: "L03 · High Performance",
      title: "High Performance band",
      lead:
        "HP raises clutter, adds offside-trap pictures, and introduces Sum — encode a red reference, then find two numbers that add to it.",
      blocks: [
        {
          type: "h2",
          text: "Players — C1",
        },
        {
          type: "p",
          text:
            "Pass among HP stills. Goal posts sit on screens 3 and 4. Some actions are offside-trap crosses — teach athletes to recognise the trap image and still choose the legal pass.",
        },
        {
          type: "table",
          headers: ["Set", "Traps"],
          rows: [
            ["C1.T1–T2", "4 trap patterns mixed in."],
            ["C1.T3–T5", "All 6 trap patterns."],
          ],
        },
        {
          type: "grid",
          cards: [
            {
              title: "Pass",
              text: "Legal target",
              image: img(
                "/static/players/high_performance/pass.png",
                "HP pass"
              ),
            },
            {
              title: "Offside trap",
              text: "Cross trap still",
              image: img(
                "/static/players/high_performance/Cross-OffSide-Trap-01-B.png",
                "trap"
              ),
            },
            {
              title: "Left post",
              text: "Post marker",
              image: img(
                "/static/players/high_performance/left_post.jpeg",
                "left post"
              ),
            },
            {
              title: "Defending",
              text: "Pressure still",
              image: img(
                "/static/players/high_performance/SIMUST-Defending-08-01-B.png",
                "defend"
              ),
            },
          ],
        },
        {
          type: "h2",
          text: "Numbers — C2",
        },
        {
          type: "p",
          text:
            "Six numbers from 1–100. Clear lowest → next lowest. Each test uses one solid background colour shared by all screens.",
        },
        {
          type: "h2",
          text: "Divergent — C3",
        },
        {
          type: "p",
          text:
            "Odd-one-out with HP styling. Middle letter / symbol emphasis on some sets. Kick the screen that does not belong.",
        },
        {
          type: "h2",
          text: "Sum — C4",
        },
        {
          type: "steps",
          items: [
            "Encode phase: a red reference number appears on all screens (T1–T2: ~4 s, T3–T5: ~3 s).",
            "Answer phase: screens show numbers. Find a pair that sums to the reference.",
            "Budget ~60 s per test for answers (6 actions × ~10 s).",
            "Kick one of the correct pair mouths using Goal Area + HIP.",
          ],
        },
      ],
    };
  }

  function pageElite() {
    return {
      kicker: "L04 · Elite",
      title: "Elite band",
      lead:
        "Elite merges Field A and Field B into one 12-screen puzzle. Players C1 mirrors Entry’s dual-field pass game with Elite artwork; later Components use 12 actions per test.",
      blocks: [
        {
          type: "h2",
          text: "Players — C1 (dual field)",
        },
        {
          type: "p",
          text:
            "Both fields light together. Pass among Elite PNGs. All listed goals on an action must score before advance on denser sets.",
        },
        {
          type: "table",
          headers: ["Set", "Images", "Pass pool", "Actions"],
          rows: [
            ["C1.T1", "6 images on 12 screens (3 / field)", "pass1 only", "10 / test"],
            ["C1.T2", "8 images on 12 screens", "pass1 only", "10 / test"],
            ["C1.T3", "12 images on 12 screens", "pass1 only", "10 / test"],
            ["C1.T4–T5", "12 images", "pass1 / pass2 / pass3 · 14 goals across 10 actions", "10 / test"],
          ],
        },
        {
          type: "grid",
          cards: [
            {
              title: "pass1",
              text: "Primary pass",
              image: img("/static/players/Elite/pass1.png", "pass1"),
            },
            {
              title: "pass2",
              text: "T4–T5 target",
              image: img("/static/players/Elite/pass2.png", "pass2"),
            },
            {
              title: "pass3",
              text: "T4–T5 target",
              image: img("/static/players/Elite/pass3.png", "pass3"),
            },
            {
              title: "Opponent",
              text: "Distractor",
              image: img(
                "/static/players/Elite/Opponent-PL-05-B.png",
                "opponent"
              ),
            },
            {
              title: "Defending",
              text: "Pressure still",
              image: img(
                "/static/players/Elite/SIMUST-Defending-08-01-B.png",
                "defend"
              ),
            },
            {
              title: "Teammate",
              text: "Friendly still",
              image: img(
                "/static/players/Elite/Teammate-PL-01-B.png",
                "teammate"
              ),
            },
          ],
        },
        {
          type: "callout",
          kind: "tip",
          html:
            "<strong>Timing on Players C1.</strong> Uses Entry timing (starts 3.0 s / 1.0 s), not the Elite number clock.",
        },
        {
          type: "h2",
          text: "Numbers — C2",
        },
        {
          type: "p",
          text:
            "12 of 22 pool numbers across A+B. Always clear the lowest remaining. Lowest-done screen can turn orange 00. On clock starts at 4.5 s; gap stays 0.5 s; each later set is 10% faster (floor ~2.5 s).",
        },
        {
          type: "table",
          headers: ["Set", "On", "Gap"],
          rows: ELITE_TIMING.map(function (r) {
            return [r.set, r.on, r.gap];
          }),
        },
        {
          type: "h2",
          text: "Divergent — C3",
        },
        {
          type: "p",
          text:
            "Odd-one-out on the combined field with symbols / shapes on later tests. Same Elite on/gap timing (S2 floor ~2.6 s).",
        },
        {
          type: "h2",
          text: "Sum — C4",
        },
        {
          type: "p",
          text:
            "Encode a red two-digit reference (&lt; 50) for 3 s, then 12 answer actions with a 120 s test budget. Find pair(s) that sum to the reference on the 12-screen field.",
        },
      ],
    };
  }

  function pageWorld() {
    return {
      kicker: "L05 · World Class",
      title: "World Class band",
      lead:
        "World Class is the top combined-field band. Wall Components start at Numbers C1 (no Players Component yet).",
      blocks: [
        {
          type: "callout",
          kind: "warn",
          html:
            "<strong>@Siamak — product ask.</strong> Please prepare a <em>World Class Players</em> scenario (art + rules), similar to Elite Players C1, so WC can gain a Players Component before Numbers. Until then, coaches start WC at Numbers C1.",
        },
        {
          type: "h2",
          text: "Numbers — C1 (internal S1)",
        },
        {
          type: "p",
          text:
            "Same 12-screen lowest-number clear as Elite, but World Class changes background colour every action and rotates digit colours for readability.",
        },
        {
          type: "h2",
          text: "Divergent — C2 (internal S2)",
        },
        {
          type: "p",
          text:
            "Odd-one-out with animated camouflage themes: flowers → fruits → animals → space → orbs across T1–T5. Harder visual search than Elite.",
        },
        {
          type: "h2",
          text: "Sum — C3 (internal S3)",
        },
        {
          type: "p",
          text:
            "Encode red reference between 51 and 99 (3 s), then 12 actions / 120 s budget. Pair sum on the combined field — larger numbers than Elite.",
        },
        {
          type: "table",
          headers: ["Component", "Wall label", "Coach one-liner"],
          rows: [
            ["Numbers", "C1.T1–T5", "Lowest of 12; colours change every action."],
            ["Divergent", "C2.T1–T5", "Find the odd screen in motion camouflage."],
            ["Sum", "C3.T1–T5", "Remember 51–99 reference; kick a summing pair."],
            ["Players", "—", "Not shipped yet — Siamak scenario pending."],
          ],
        },
        {
          type: "callout",
          kind: "",
          html:
            "<strong>End of path.</strong> World Class Sum C3.T5 is currently the final unlock in the development ladder.",
        },
      ],
    };
  }

  function pageUnlock() {
    return {
      kicker: "Progression",
      title: "Unlock & level-up",
      lead:
        "Athletes move set-by-set. Finals after a set decide whether the next Component / band opens.",
      blocks: [
        {
          type: "h2",
          text: "Unlock thresholds",
        },
        {
          type: "table",
          headers: ["Band", "Gate"],
          rows: [
            ["Foundation", "AE ≥ 65%"],
            ["Entry → World Class", "AE ≥ 70% (ACC does not gate unlock)"],
          ],
        },
        {
          type: "h2",
          text: "Band hand-offs (examples)",
        },
        {
          type: "table",
          headers: ["After you pass…", "Next opens…"],
          rows: [
            ["Last Foundation playlist", "Entry Players C1.T1"],
            ["Entry Numbers last set", "Activated Players C1.T1"],
            ["Activated Divergent last set", "HP Players C1.T1"],
            ["HP Sum last set", "Elite Players C1.T1"],
            ["Elite Sum last set", "World Class Numbers C1.T1"],
            ["World Class Sum last set", "End of ladder"],
          ],
        },
        {
          type: "p",
          text:
            "Inside a band, T1→T2→…→T5 unlock in order for each Component, then the next Component starts at T1.",
        },
        {
          type: "callout",
          kind: "tip",
          html:
            "<strong>Promotion clips.</strong> When a band opens, a short wall video can play (foundation_to_entry, entry_to_activated, … elite_to_world_class).",
        },
      ],
    };
  }

  function pageTiming() {
    return {
      kicker: "Reference",
      title: "Timing tables",
      lead:
        "Keep this page open while coaching if athletes ask “how long do I have?”",
      blocks: [
        {
          type: "h2",
          text: "Shared results timing (all bands)",
        },
        {
          type: "table",
          headers: ["Phase", "Duration"],
          rows: [
            ["Processing animation", "~4.0 s"],
            ["Results rings on wall", "~4.0 s"],
          ],
        },
        {
          type: "h2",
          text: "Entry / Activated / HP Players cue clock",
        },
        {
          type: "table",
          headers: ["Set", "On", "Gap"],
          rows: ENTRY_TIMING.map(function (r) {
            return [r.set, r.on, r.gap];
          }),
        },
        {
          type: "h2",
          text: "Elite / World Class Numbers & Divergent",
        },
        {
          type: "table",
          headers: ["Set", "On", "Gap"],
          rows: ELITE_TIMING.map(function (r) {
            return [r.set, r.on, r.gap];
          }),
        },
        {
          type: "h2",
          text: "Sum encode & budgets",
        },
        {
          type: "table",
          headers: ["Band", "Encode", "Answer budget", "Actions"],
          rows: [
            ["HP Sum", "4 s (T1–T2) / 3 s (T3–T5)", "~60 s / test", "6"],
            ["Elite Sum", "3 s every set", "~120 s / test", "12"],
            ["World Class Sum", "3 s every set", "~120 s / test", "12"],
          ],
        },
        {
          type: "p",
          text:
            "Live finish_balls cues can wait longer than the nominal On time until a valid Goal Area direction-change finish is recorded (or Wrong).",
        },
      ],
    };
  }

  function pageManual() {
    return {
      kicker: "Operator tool",
      title: "Manual Coach",
      lead:
        "Manual lets you light Goal Areas yourself for demonstration — useful before a first Entry session.",
      blocks: [
        {
          type: "steps",
          items: [
            "Open the Manual tab.",
            "Press Start Manual (camera / player warm in the background).",
            "Press Area A and/or Area B to open that half’s camera view.",
            "Tap a mouth (A1–A6 / B1–B6) to show a Foundation-sized pass + Goal Area together.",
            "Stop Manual when the demo is done — the session video is saved like a normal Play Stop.",
          ],
        },
        {
          type: "callout",
          kind: "tip",
          html:
            "<strong>Teaching tip.</strong> Show one Correct Goal Area bounce/return finish in Manual before starting Entry Players so athletes know what “in” feels like. The camera recording is kept when you Stop Manual.",
        },
      ],
    };
  }

  function pageTips() {
    return {
      kicker: "Floor craft",
      title: "Quick tips for coaches",
      lead: "Short reminders that save session time.",
      blocks: [
        {
          type: "h2",
          text: "Before Play",
        },
        {
          type: "steps",
          items: [
            "Confirm the athlete’s unlocked Component on the booking / progress.",
            "Restart Realtime Play after Goal Area or HIP calibration changes.",
            "Explain the one rule for the set in one sentence (examples below).",
          ],
        },
        {
          type: "table",
          headers: ["Set type", "One sentence"],
          rows: [
            ["Players", "Only kick the pass image — ignore everyone else."],
            ["Numbers", "Always clear the lowest number left on the wall."],
            ["Divergent", "Kick the screen that does not belong."],
            ["Sum", "Remember the red number, then kick a pair that adds to it."],
            ["Offside traps (HP)", "If you see the trap cross, stay disciplined — still pick the legal pass."],
          ],
        },
        {
          type: "h2",
          text: "During Play",
        },
        {
          type: "p",
          text:
            "If Wrong repeats on the same mouth, check ball depth into the Goal Area, not only kick power. If one field is done, you can Stop that field while the other continues (independent mode).",
        },
        {
          type: "h2",
          text: "After finals",
        },
        {
          type: "p",
          text:
            "Watch for unlock of the next T-set or band. Celebrate briefly, then restate the new rule if the Component changed (Players → Numbers, etc.).",
        },
      ],
    };
  }

  var PAGES = {
    welcome: pageWelcome,
    basics: pageBasics,
    "field-goals": pageFieldGoals,
    "level-map": pageLevelMap,
    foundation: pageFoundation,
    entry: pageEntry,
    activated: pageActivated,
    hp: pageHp,
    elite: pageElite,
    world: pageWorld,
    unlock: pageUnlock,
    timing: pageTiming,
    manual: pageManual,
    tips: pageTips,
  };

  var PAGE_IDS = NAV.filter(function (n) {
    return n.id;
  }).map(function (n) {
    return n.id;
  });

  function renderBlocks(blocks) {
    return (blocks || []).map(function (b, idx) {
      if (b.type === "p") {
        return h("p", { key: idx }, b.text);
      }
      if (b.type === "h2") {
        return h("h2", { key: idx }, b.text);
      }
      if (b.type === "h3") {
        return h("h3", { key: idx }, b.text);
      }
      if (b.type === "callout") {
        return h("div", {
          key: idx,
          className: "coach-guide-callout" + (b.kind ? " " + b.kind : ""),
          dangerouslySetInnerHTML: { __html: b.html },
        });
      }
      if (b.type === "steps") {
        return h(
          "ol",
          { key: idx, className: "coach-guide-steps" },
          b.items.map(function (item, i) {
            return h("li", { key: i }, item);
          })
        );
      }
      if (b.type === "map") {
        return h(
          "div",
          { key: idx, className: "coach-guide-map" },
          b.items.map(function (it, i) {
            return h("span", { key: i }, h("em", null, it.em), it.text);
          })
        );
      }
      if (b.type === "grid") {
        return h(
          "div",
          { key: idx, className: "coach-guide-grid" },
          b.cards.map(function (c, i) {
            return h(
              "div",
              { key: i, className: "coach-guide-card" },
              c.image
                ? h("img", {
                    src: c.image.src,
                    alt: c.image.alt,
                    loading: "lazy",
                  })
                : null,
              h("h4", null, c.title),
              h("p", null, c.text)
            );
          })
        );
      }
      if (b.type === "figure") {
        return h(
          "figure",
          { key: idx, className: "coach-guide-figure" },
          h("img", { src: b.image.src, alt: b.image.alt, loading: "lazy" }),
          b.caption ? h("figcaption", null, b.caption) : null
        );
      }
      if (b.type === "table") {
        return h(
          "div",
          { key: idx, className: "coach-guide-table-wrap" },
          h(
            "table",
            null,
            h(
              "thead",
              null,
              h(
                "tr",
                null,
                b.headers.map(function (hd, i) {
                  return h("th", { key: i }, hd);
                })
              )
            ),
            h(
              "tbody",
              null,
              b.rows.map(function (row, ri) {
                return h(
                  "tr",
                  { key: ri },
                  row.map(function (cell, ci) {
                    return h("td", {
                      key: ci,
                      dangerouslySetInnerHTML:
                        typeof cell === "string" && cell.indexOf("<") >= 0
                          ? { __html: cell }
                          : undefined,
                    }, typeof cell === "string" && cell.indexOf("<") >= 0
                      ? null
                      : cell);
                  })
                );
              })
            )
          )
        );
      }
      return null;
    });
  }

  function CoachGuidePanel() {
    var pageState = useState("welcome");
    var pageId = pageState[0];
    var setPageId = pageState[1];
    var mainRef = useRef(null);

    useEffect(
      function () {
        if (mainRef.current) {
          mainRef.current.scrollTop = 0;
        }
      },
      [pageId]
    );

    var factory = PAGES[pageId] || pageWelcome;
    var page = factory();
    var idx = PAGE_IDS.indexOf(pageId);

    return h(
      "div",
      { className: "coach-guide-shell" },
      h(
        "div",
        { style: { marginBottom: 14 } },
        h(
          "div",
          {
            style: {
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
              alignItems: "center",
              justifyContent: "space-between",
            },
          },
          h(
            "div",
            null,
            h(
              "h2",
              { className: "text-2xl font-black gold-accent", style: { margin: 0 } },
              "Coach Guide"
            ),
            h(
              "p",
              {
                style: {
                  margin: "6px 0 0",
                  color: "#9eacc0",
                  fontSize: 13,
                  maxWidth: "62ch",
                },
              },
              "Handbook for running every SIMUST band — scenarios, timings, and unlock path."
            )
          ),
          h("span", { className: "coach-guide-badge gold" }, "Docs")
        )
      ),
      h(
        "select",
        {
          className: "coach-guide-mobile-select",
          value: pageId,
          onChange: function (e) {
            setPageId(e.target.value);
          },
        },
        PAGE_IDS.map(function (id) {
          var item = NAV.filter(function (n) {
            return n.id === id;
          })[0];
          return h("option", { key: id, value: id }, item ? item.label : id);
        })
      ),
      h(
        "div",
        { className: "coach-guide" },
        h(
          "nav",
          { className: "coach-guide-nav", "aria-label": "Guide sections" },
          h("div", { className: "coach-guide-nav-title" }, "Contents"),
          NAV.map(function (item, i) {
            if (item.group) {
              return h(
                "div",
                { key: "g" + i, className: "coach-guide-nav-group" },
                item.group
              );
            }
            return h(
              "button",
              {
                key: item.id,
                type: "button",
                className: pageId === item.id ? "active" : "",
                onClick: function () {
                  setPageId(item.id);
                },
              },
              item.label
            );
          })
        ),
        h(
          "main",
          { className: "coach-guide-main", ref: mainRef },
          h("div", { className: "coach-guide-kicker" }, page.kicker),
          h("h1", null, page.title),
          page.lead ? h("p", { className: "coach-guide-lead" }, page.lead) : null,
          renderBlocks(page.blocks),
          h(
            "div",
            { className: "coach-guide-pager" },
            h(
              "button",
              {
                type: "button",
                disabled: idx <= 0,
                onClick: function () {
                  if (idx > 0) setPageId(PAGE_IDS[idx - 1]);
                },
              },
              "← Previous"
            ),
            h(
              "button",
              {
                type: "button",
                disabled: idx < 0 || idx >= PAGE_IDS.length - 1,
                onClick: function () {
                  if (idx >= 0 && idx < PAGE_IDS.length - 1) {
                    setPageId(PAGE_IDS[idx + 1]);
                  }
                },
              },
              "Next →"
            )
          )
        )
      )
    );
  }

  global.CoachGuidePanel = CoachGuidePanel;
})(window);
