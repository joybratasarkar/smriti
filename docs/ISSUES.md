# Issues

Everything broken, weak or undecided, and whether it can be fixed. IDs are permanent and never reused.

- **Type:** `bug` (broken), `quality` (measured weakness), `question` (open design question; once answered it closes here and the answer goes to [DECISIONS.md](DECISIONS.md)), `chore` (environment upkeep).
- **Priority:** P1 blocks the next step, P2 matters soon, P3 whenever.
- **Status:** `open` → `in progress` → `solved` / `won't fix`, or `blocked` (on what).
- **Solvable?:** `yes` / `partly` / `no` / `unknown`.

## Open

| ID | Title | Type | P | Status | Solvable? | Next action |
|---|---|---|---|---|---|---|
| I-001 | Grouping gives event-level clusters, not issues | question | P1 | in progress | yes | 2026-10-25 regroup: CJP is now 3 big stories (was 165), the largest 1,820 articles over 2 months with some SIR / election-commission news mixed in; check story 8 for drift |
| I-016 | One event split into parallel stories (Nepal floods: 8 stories) | quality | P1 | in progress | yes | 2026-10-25 regroup: Nepal, flydubai, *Toxic* now 1 story each; stories' recall 0.67 → 0.70 (0.75 counting links). Next: the 18 gold pairs still split, 15 with no link (`logs/gold3.out`) |
| I-002 | LLM `who` field has wrong or invented entries | quality | P1 | in progress | partly | Hand-check the 2026-10-20 run |
| I-003 | Wrong `action_type`; `arrest_detention` overused | quality | P2 | in progress | yes | Hand-check the 2026-10-20 run |
| I-004 | Speculation ("could be arrested") stored as fact | quality | P2 | in progress | yes | Hand-check the 2026-10-20 run |
| I-005 | Same event listed twice in one article | quality | P3 | open | unknown | Measure in the hand check |
| I-011 | Leftover `nvidia-driver-535` package | chore | P3 | open | yes | `sudo apt remove nvidia-driver-535` after checking it isn't in use |
| I-012 | Git warns `credential-manager-core` is not a git command | chore | P3 | open | yes | `git config --global --unset credential.helper` (push works without it) |
| I-015 | Daily columns (horoscope, quote of the day) chain into giant "stories" | quality | P2 | in progress | yes | 2026-10-25 regroup: largest horoscope story still 19, quote of the day 6 (was 12); decide whether to leave such columns out of grouping |
| I-018 | Different incidents of the same kind chain into one story (campus deaths: 158 articles) | quality | P2 | in progress | partly | 2026-10-25 regroup: IIT-Bombay (182, 176 about IIT-B) and IIT Delhi (60) are separate, a few other campus suicides still inside; the gold check finds 2 such joins (puja pandal checks, daily gold prices) |
| I-022 | AI titles can state a false fact the name-and-number check lets through ("Tiger Shroff shot in Juhu"; he was shot at and unhurt) | quality | P1 | in progress | partly | LLM referee added 2026-10-26 (titles and dot labels must be backed by their headlines); stored ones rechecked. Next: hand-check a sample of what it keeps; it still missed "schools bombed" for bomb threats |
| I-025 | Category classifier agrees with the LLM on only ~70% of articles; Sports almost never predicted | quality | P2 | in progress | partly | Front-page stories are labelled by the LLM itself (D-036); for the rest, label more Sports / Health / Tech articles or a story-level classifier |

## Details (open)

### I-015 · Daily columns become giant stories
- **Evidence (2026-10-20 smoke test, first 4,000 articles):** "Horoscope Today, August 23" collected 202 articles and "Quote of the Day" 21: each day's column is close to the previous day's, so they chain into one story.
- **Fix idea:** leave recurring columns out of grouping (URL paths like `/astrology/`, title patterns like "Horoscope Today"), or cap a story's daily growth from one source.
- **Update (2026-10-20 full regroup with the fine-tuned cross-encoder, Aug 21 – Sep 1 so far):** no horoscope story has more than 9 articles. The teacher labels look-alike columns `same_topic`, and the student learned it. Confirm when the regroup ends.
- **Full regroup done (2026-10-20, all 60 days):** much better, not gone. 3,501 stories have "horoscope" in the label; the largest has 19 articles, one a day for 19 days (Sep 8–26). The largest Quote of the Day story has 12 (11 days). Before the fine-tuned model: 202 and 21. A column still chains for one to three weeks before the student says no.

### I-016 · One event split into parallel stories
- **Evidence (2026-10-20 full regroup, Aug 21 – Sep 1 so far):** the Nepal floods became 4 stories (167, 133, 60 and 58 articles, all Aug 26/27 – Sep 1); the *Toxic* box office 2 stories (77 and 71). By Sep 22 the four Nepal stories had 191, 177, 88 and 73 articles, and their centres are almost identical: cosine 0.92 to 0.99 between each pair.
- **Likely cause:** the cross-encoder was trained on article-vs-article pairs, but `app.group` shows it the article against a story's 3 latest headlines joined together. And once two stories exist, nothing merges them, because assigned articles never move.
- **Confirmed in one case by an exact replay (2026-10-20):** the second Nepal story (issue 7797, 177 articles) started at 26 Aug 17:45 with "Over 50 Tamil Nadu pilgrims stranded after flash floods at Nepal-China border" (hindustantimes.com). Its top candidate was the first Nepal story (cosine 0.761), but that story's 3 latest headlines were about the cause, PM Modi's call and the US advisory; its own pilgrims headline had just been pushed out by two newer articles. The cross-encoder scored every candidate below 0.5, so the article started a new story. The replay rebuilds each story's centre from the articles assigned before it and reproduces the stored cosines.
- **Real scores, recomputed with the same inputs (2026-10-20):** at the split the student gave the first Nepal story **0.404**, just under the 0.5 cut-off. With the window that still held the pilgrims headline it gives 0.96, and against that one headline alone 0.983. The same recomputation reproduces the stored scores (0.98 for the example join; link weights 0.984, 0.965, 0.597).
- **Links have the same weakness:** Nepal 7797–8092 and 7797–8008 were link candidates, but their weights were 0.144 and 0.099 (below 0.2, dropped), although both pairs are Nepal floods stories with centre cosine 0.966 and 0.921. The weight comes from the cross-encoder before fine-tuning, reading only each story's 3 latest headlines: 7797's are about why Nepal floods keep happening, an evacuation call and Indian aid; 8092's are three copies of "Nepal cuts 12-year wait to declare flood missing dead".
- **Full regroup done (2026-10-20, all 60 days):** the Nepal floods are in 8 stories of 20 or more articles (191, 179, 95, 84, 62, 27, 25 and 22: 685 articles). The CJP protest's 1,380 headlines are in 165 stories (I-001). The flydubai incident is in 5 stories of 50 or more, and the *Toxic* box office in 2 (107 and 86, centre cosine 0.970).
- **What the links show:** the LLM named 66 of the 500 strongest links `same_story`, among them 4 Nepal pairs (7438–7797: weight 0.984, centre cosine 0.990). Most split pairs are not named, and some are not linked at all: only the 500 strongest links were named, and Nepal 7797–8092 (centre cosine 0.966) has no link. The biggest CJP story (2955, 224 articles) has one link.
- **Measured on the gold set (2026-10-20, Claude's labels, D-029):** of 48 same-story pairs, the app's stories keep 32 together; 16 are split, and 14 of those have no link between their stories either. The student alone, scoring each pair at 0.5, would keep 39 of 48 (recall 0.81 against 0.67), so most of the loss comes from how grouping uses it (3 latest headlines, no merging), not from the model.
- **Not every `same_story` name is right:** "Tech layoffs 2026" is named `same_story` with four separate Oracle and Amazon layoff stories (centre cosine 0.68 to 0.72). Merging on the LLM's name alone would join different events.
- **Fix proposed (2026-10-20, needs the user's OK):** (1) compare a new article with the story's 3 closest articles instead of its 3 latest headlines, the same kind of pair the student was trained on; (2) after grouping, a merge pass over story pairs with centre cosine ≥ 0.9: the student reads their closest articles, and the two merge when it says same story. Then regroup all 60 days (about 5 hours).
- **2026-10-25 regroup (D-034, D-035; merge pass merged 197 stories):** Nepal floods 1 story of 20+ (695 articles, was 8), flydubai 1 (344, was 5), *Toxic* box office 1 (was 2), CJP 3 (788, 91 and 54 CJP headlines; was 165 stories). Gold check (`logs/gold3.out`, 245 pairs): precision 0.86 → 0.91, recall 0.67 → 0.70, 0.75 counting any link. 18 same-story pairs still split, 15 of them with no link: mostly two takes on one small item (two Fed officials on inflation, one Alia Bhatt outfit, one novel reviewed twice). The student alone keeps 0.82 of them, so grouping still loses some.

### I-001 · Event-level clusters, not issues
- **Evidence:** at cosine 0.70, 87 separate "issues" in the DB are all the CJP / Jantar Mantar protest.
- **Root cause:** similarity of title + snippet captures the event ("trains cancelled"), not the shared story behind it.
- **Plan:** D-024: two-tower retrieval + fine-tuned cross-encoder gives link type and weight; LLM labels and referees. Chosen by a gold-set comparison.
- **Full regroup with the fine-tuned model (2026-10-20):** 1,380 headlines mention CJP or Abhijeet Dipke; they are in 165 stories, the largest holding 176. Stories whose label mentions CJP or Jantar Mantar: 112 (the old count, 87, was on far fewer articles, with cosine 0.70). The stories are bigger (several with 100 or more articles) but still event-sized: the march, the detentions, the airport arrest, the court custody. The links connect only a few of them (I-016).
- **2026-10-25 regroup:** the CJP protest is now one main story (issue 8: 1,820 articles, 21 Aug – 25 Oct, 788 headlines naming CJP) plus two smaller. A sample of the rest is mostly the protest (Jantar Mantar, detentions, metro closures, Abhijeet Dipke), but some SIR / chief-election-commissioner news has joined. Next: check whether that drift is one story by D-013 or should split off.

### I-002 · `who` errors
- **Evidence (2026-10-20 hand check, 50 events, Oct 10 run):** invented acronym expansion "CJP (Chief Judicial Panel)"; non-entities "Facial Recognition System (FRS)", "Baliyan's brother"; "the government" turned into "Government of Delhi"; typo "Ashutosh Rank".
- **Progress:** prompt rules (D-020). Oct 20 rerun: only "Facial Recognition System (FRS)" left in an automatic scan of 100 events; not yet checked by hand.
- **Why only partly solvable:** a 4B model will keep making some name errors; `entity_aliases` (D-015) absorbs spelling variants, and outlets themselves spell names differently.

### I-003 · Wrong `action_type`
- **Evidence:** ~8 of 50 wrong in the Oct 10 run: statements, demands and warnings labelled `arrest_detention` or `policy_decision`; a court petition labelled `police_action`. Oct 20 run: `arrest_detention` 26 of 100.
- **Progress:** `demand` and `warning` added (D-020); used 5 and 3 times in the Oct 20 run.

### I-004 · Speculation stored as fact
- **Evidence:** Oct 10 run, article 183: "could be arrested" stored as an `arrest_detention` event.
- **Progress:** prompt rule (D-020). Oct 20 run: the 3 "could / will" events left are all statements by named people, which the rule allows.

### I-005 · Duplicate events
- **Evidence:** Oct 10 run, article 121: events 1 and 2 are the same detention of Deepak Baliyan.
- **Progress:** prompt rule (D-020); not measured yet.

### I-018 · Similar incidents chain into one story
- **Evidence (2026-10-20 full regroup):** issue 941 (158 articles, Aug 21 – Oct 5) holds several separate deaths: an IISc student in Bengaluru, a nursing student in a Delhi hostel, IIT Delhi students, and the IIT-Bombay protests. By the D-013 definition these are different stories on the same topic.
- **Likely cause:** the same as I-015. A new article is compared with the story's 3 latest headlines, so a story can drift from one incident to the next.
- **Next:** measure how often this happens on the gold set; fixes would be a higher join cut-off or more training pairs of this kind.
- **2026-10-25 regroup:** IIT-Bombay student death (issue 39443, 182 articles, 176 about IIT-B) and IIT Delhi (issue 2074, 60) are now separate stories; a few other campus suicides (a Kolkata BBA student, an NTF report) are still inside 39443. Gold check: 4 pairs wrongly together, 2 of this kind (two puja pandal safety drives; two days of MCX gold prices), plus a same-actor (Mani Ratnam films) and a same-topic (two trade opinion pieces).

### I-022 · AI titles can state a false fact
- **Evidence (2026-10-25, `logs/front_titles.out`):** the lead story's title "Tiger Shroff shot in Juhu, others injured" passed the check, but the headlines say "escapes firing attempt", "shot at", "escapes unhurt"; the driver and a passerby were injured. Deleted from `story_titles` by hand, so the card shows the trimmed headline.
- **Cause:** `moments.safe` only checks that names and numbers appear in the headlines, not what the words claim. Dot labels (D-030) use the same check.
- **To check:** "France protests turn violent, 2400 arrested" (the central headline says 1,800), "Houthis attack Saudi targets, Egypt supports", "Netanyahu warns of hostile US, seeks India ties".
- **2026-10-25 run:** `app.front --titles 60` on the new stories: 50 titles written, 10 failed the check (headline shown), e.g. "Trump pledges $5,000 to all adults if GOP wins midterms", "Delhi Protests: 500+ Detained Ahead of CJP Rally". Dot labels for the 300 biggest stories: 1,882 written, 185 failed the check.
- **Fix (2026-10-26):** `moments.supported`: the LLM as referee copies the headline that best backs the title, then says `fine` or `wrong`; a title may summarise and leave details out, but not state a fact the headlines contradict or never say. Used for front titles and dot labels, after `safe()`. A first version that named the unsupported claim first rejected all 53 titles; the evidence-first one, on the 53 front titles plus 4 planted false ones, rejected both Tiger Shroff titles, 2 of 4 planted ones ("Iran kills U.S. officials", "Ashoke Sen rejects Oskar Klein Medal"; `safe()` catches a changed number), "Neha Bora Rejects Peace Bond Order" (the court only reserved its order), a Diljit Dosanjh concert title with conflicting headlines, and one false alarm ("Russia and Ukraine launch drone attacks"). It missed "Delhi schools bombed" for bomb threats. Rechecking the stored titles removed 4 of 53; the lead story now reads "Tiger Shroff Targeted in Mumbai Shooting". Rechecking the stored dot labels (`logs/recheck_labels.out`) removed 78 of 1,888, e.g. "High court stays bypolls in Tamil Nadu" (it declined to), "Fairfax plans exit to fund IDBI bid" (IIFL dismissed the report), "Tesla Roadster can fly and land safely", "Muskan to be hanged at Mathura jail" (only if the sentence is upheld); some look like false alarms ("Rajinikanth's Jailer 2 hits ₹500 crore"), which only means the headline shows. `app.moments --label 300` then wrote 61 new labels through the referee; 233 moments failed the check and show their headline.

### I-025 · Category classifier is weak
- **Evidence (2026-10-26, `logs/categories.out`):** 1500 LLM-labelled articles (one per story). Softmax regression on bge-m3 vectors, 5-fold: 71.4% agreement with the LLM (Business 83%, Crime 79%, Politics 75%, Society 69%, Tech 56%, Environment 56%, Entertainment 55%, Health 34%, Sports 0%). Class weights, scaling and k-NN gave 64–69%. It labels only 17 of 83,607 stories Sports.
- **Cause:** few examples of the rare categories (Sports 12, Health 41) because sport is rare in our feeds and the sample is one article per story; a single headline's vector mixes subject with place and people.
- **Teacher on 80 articles checked by Claude:** 74/80 with the "about" prompt; still weak on Sports (athletes honoured by politicians go to Society) and on accidents (a car running over labourers went to Society or Crime).
- **Workaround (D-036):** the ~550 front-page stories are labelled by the LLM from their main headlines (`python -m app.categories --stories`); the classifier only fills the rest.

## Closed

| ID | Title | Type | Closed | How |
|---|---|---|---|---|
| I-024 | Dot labelling crashed on an empty LLM answer | bug | 2026-10-25 | `app.moments` read the answer with `json.loads` unguarded; at 22:39 one empty reply ended the run before titles and the gold check. An unreadable answer now counts as a failed check (headline shown), like `app/judge.py`; resumed with `logs/run_2026-10-25b.sh`, labels already written kept |
| I-023 | One shared name carries a new event into an old story (Tiger Shroff shooting in the FDA ad-notice story) | quality | 2026-10-26 | D-034 + D-035: teacher relabelled with hard-case rules, 1000 shared-name pairs, student retrained, per-headline scoring, full regroup. Shooting is its own story (314 articles, 0 FDA); student 93.5% on gold, same-actor pairs wrongly joined 2 of 21 |
| I-019 | The same article is stored twice under different URLs (903 extra) | bug | 2026-10-26 | D-031 fix applied by the 2026-10-25 regroup: 1 repeated outlet + headline + day left in the stories (was 903) |
| I-017 | 64 GDELT articles have a blank title; 56 of them form one junk story | bug | 2026-10-26 | D-031 fix applied by the 2026-10-25 regroup: no blank-title article is grouped, no blank-label story |
| I-020 | One outlet shown under two names (21 names for 15 sites) | bug | 2026-10-24 | The API shows one name per site: a GDELT row gets the feed's name for its site (`moments.outlet_names`), and source counts use sites (header 21 → 15). The stored `source_name` is unchanged; BBC's three feeds keep their own names |
| I-021 | Every story said "No reports found since …" when the data was stale | bug | 2026-10-24 | "Quiet" is measured against the last fetch, not today, and the status says when the news was checked: "No new reports since 9 Sept · news checked up to 20 Oct" (D-030) |
| I-007 | Ollama killed by the out-of-memory killer | bug | 2026-10-20 | Ollama's prompt cache (8 GiB default) filled the 7.1 GB of RAM. Turned off (`LLAMA_ARG_CACHE_RAM=0`, systemd drop-in) plus a retry in code. The full run (2,960 teacher labels, 500 link names) had no OOM kill |
| I-006 | Quotes not word for word | quality | 2026-10-20 | Two causes: checker too strict on `…`/`[ ]`, and quotes built from split sentences. Checker fixed, prompt rule added, unverified quotes dropped (D-019). Verified 77% → 92% |
| I-008 | `TECHNICAL.md` accidentally edited (stray `y`, "swap them" replacing a section) | bug | 2026-10-20 | Restored from the last commit |
| I-009 | Data is stale: last fetch 2026-10-10 | chore | 2026-10-20 | RSS fetched and the 60-day GDELT backfill done (D-026): 138,229 articles, Aug 21 – Oct 20, all embedded |
| I-010 | GDELT returns 429s and empty results | chore | 2026-10-10 | Won't fix: GDELT kept opt-in (D-001) |
| I-013 | Secure Boot blocked the NVIDIA driver | chore | 2026-10-10 | MOK key enrolled; driver 595.99 / CUDA 13.2; Ollama upgraded to 0.40.2 |
| I-014 | Qwen3.5-4B doesn't fit in 4 GB VRAM | bug | 2026-10-10 | Switched to Qwen3-4B-Instruct-2507 (D-017) |
