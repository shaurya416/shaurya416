# checks

Every number this build computes from data/ and the field it is read from (data/stats.json unless another file is named).
Written by `python3 build.py`, which fails if a value listed here is missing from the output it names.
Panel values are looked up in the SVG text and its description; README values on the line they belong to.
Figures the prose quotes from elsewhere are listed after the table, with their sources.

| where | what | value as shown | field |
|:--|:--|:--|:--|
| filed panel | issues filed | 238 | `issues.total` |
| filed panel | issues fixed | 20 | `outcomes.fixed_by_merged_pr_from_someone_else + outcomes.fixed_by_his_own_merged_pr` |
| filed panel | window | 2026-09-23/2026-10-08 | `issues.first_created_at, as_of` |
| filed panel | filed, 09-23 | 09-23 57 | `issues.daily_utc[day]` |
| filed panel | filed, 09-24 | 09-24 44 | `issues.daily_utc[day]` |
| filed panel | filed, 09-25 | 09-25 35 | `issues.daily_utc[day]` |
| filed panel | filed, 09-26 | 09-26 40 | `issues.daily_utc[day]` |
| filed panel | filed, 09-27 | 09-27 4 | `issues.daily_utc[day]` |
| filed panel | filed, 09-28 | 09-28 15 | `issues.daily_utc[day]` |
| filed panel | filed, 09-29 | 09-29 0 | `issues.daily_utc[day]` |
| filed panel | filed, 09-30 | 09-30 38 | `issues.daily_utc[day]` |
| filed panel | filed, 10-01 | 10-01 5 | `issues.daily_utc[day]` |
| filed panel | filed, 10-02 | 10-02 0 | `issues.daily_utc[day]` |
| filed panel | filed, 10-03 | 10-03 0 | `issues.daily_utc[day]` |
| filed panel | filed, 10-04 | 10-04 0 | `issues.daily_utc[day]` |
| filed panel | filed, 10-05 | 10-05 0 | `issues.daily_utc[day]` |
| filed panel | filed, 10-06 | 10-06 0 | `issues.daily_utc[day]` |
| filed panel | filed, 10-07 | 10-07 0 | `issues.daily_utc[day]` |
| filed panel | filed, 10-08 | 10-08 0 | `issues.daily_utc[day]` |
| filed panel | fixed, 09-24 (squares) | 09-24 1 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 09-25 (squares) | 09-25 2 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 09-27 (squares) | 09-27 1 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 09-28 (squares) | 09-28 3 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 09-29 (squares) | 09-29 2 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 09-30 (squares) | 09-30 3 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 10-01 (squares) | 10-01 2 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 10-02 (squares) | 10-02 1 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 10-03 (squares) | 10-03 1 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 10-06 (squares) | 10-06 1 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 10-07 (squares) | 10-07 2 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| filed panel | fixed, 10-08 (squares) | 10-08 1 | `fixes_by_others[].merged_at, prs.merged_list[].merged_at` |
| outcome panel | fixed, of total | of 238 fixed | `issues.total` |
| outcome panel | others | 17 | `outcomes.fixed_by_merged_pr_from_someone_else` |
| outcome panel | others, share | 7.1% | `outcomes.fixed_by_merged_pr_from_someone_else / issues.total` |
| outcome panel | own | 3 | `outcomes.fixed_by_his_own_merged_pr` |
| outcome panel | own, share | 1.3% | `outcomes.fixed_by_his_own_merged_pr / issues.total` |
| outcome panel | nofix | 5 | `outcomes.closed_not_planned + outcomes.closed_completed_without_a_fix_merged` |
| outcome panel | nofix, share | 2.1% | `(outcomes.closed_not_planned + outcomes.closed_completed_without_a_fix_merged) / issues.total` |
| outcome panel | open | 213 | `outcomes.open` |
| outcome panel | open, share | 89.5% | `outcomes.open / issues.total` |
| outcome panel | hours, n | 17 | `fix_lag_hours_filed_to_merge.n` |
| outcome panel | hours, min | 4.7 | `fix_lag_hours_filed_to_merge.min` |
| outcome panel | hours, median | 109.5 | `fix_lag_hours_filed_to_merge.median` |
| outcome panel | hours, max | 316.2 | `fix_lag_hours_filed_to_merge.max` |
| areas panel | repositories | 229 | `issues.distinct_repos` |
| areas panel | areas | 15 areas | `len(ecosystems)` |
| areas panel | eval harnesses &amp; benchmarks | eval harnesses &amp; benchmarks 42 | `ecosystems[0].issues` |
| areas panel | judge, RAG &amp; hallucination scoring | judge, RAG &amp; hallucination scoring 29 | `ecosystems[1].issues` |
| areas panel | RL post-training &amp; rewards | RL post-training &amp; rewards 22 | `ecosystems[2].issues` |
| areas panel | agent &amp; tool-use benchmarks | agent &amp; tool-use benchmarks 21 | `ecosystems[3].issues` |
| areas panel | classic metric libraries | classic metric libraries 20 | `ecosystems[4].issues` |
| areas panel | eval platforms &amp; app frameworks | eval platforms &amp; app frameworks 19 | `ecosystems[5].issues` |
| areas panel | fairness, calibration &amp; uncertainty | fairness, calibration &amp; uncertainty 18 | `ecosystems[6].issues` |
| areas panel | code &amp; math answer checking | code &amp; math answer checking 13 | `ecosystems[7].issues` |
| areas panel | data pipelines &amp; ML monitoring | data pipelines &amp; ML monitoring 12 | `ecosystems[8].issues` |
| areas panel | safety, red-teaming &amp; guardrails | safety, red-teaming &amp; guardrails 12 | `ecosystems[9].issues` |
| areas panel | autograders &amp; education | autograders &amp; education 8 | `ecosystems[10].issues` |
| areas panel | forecasting &amp; anomaly detection | forecasting &amp; anomaly detection 8 | `ecosystems[11].issues` |
| areas panel | retrieval &amp; recommender metrics | retrieval &amp; recommender metrics 7 | `ecosystems[12].issues` |
| areas panel | explainability | explainability 4 | `ecosystems[13].issues` |
| areas panel | speech &amp; audio | speech &amp; audio 3 | `ecosystems[14].issues` |
| areas panel | folded areas, issues | 22 issues | `sum of ecosystems[11:].issues` |
| areas panel | folded areas, repositories | 21 | `sum of ecosystems[11:].repos` |
| probe panel | checks that reproduce | 5 of 9 | `probe.json: len(runs[0].findings) of len(runs[0].checks_run)` |
| probe panel | after the one-line fix | 0 of 9 | `probe.json: len(runs[1].findings) of len(runs[1].checks_run)` |
| probe panel | empty\_reference, inputs that earned credit (in the description) | 3 inputs | `probe.json: runs[0].findings[0].n` |
| probe panel | unrelated\_answer, inputs that earned credit (in the description) | 2 inputs | `probe.json: runs[0].findings[1].n` |
| probe panel | substring\_containment, inputs that earned credit (in the description) | 33 inputs | `probe.json: runs[0].findings[2].n` |
| probe panel | numeric\_tolerance, inputs that earned credit (in the description) | 11 inputs | `probe.json: runs[0].findings[3].n` |
| probe panel | numeric\_sign, inputs that earned credit (in the description) | 6 inputs | `probe.json: runs[0].findings[4].n` |
| README defect table | row 1, report | \#1020 | `notes.json: rows[0].issue` |
| README defect table | row 1, fix | \#1021 | `prs.merged_list[].number` |
| README defect table | row 2, report | \#1757 | `notes.json: rows[1].issue` |
| README defect table | row 2, fix | \#1758 | `fixes_by_others[].pr` |
| README defect table | row 3, report | \#1783 | `notes.json: rows[2].issue` |
| README defect table | row 3, fix | \#1785 | `fixes_by_others[].pr` |
| README defect table | row 4, report | \#1202 | `notes.json: rows[3].issue` |
| README defect table | row 4, fix | \#1203 | `fixes_by_others[].pr` |
| README defect table | row 5, report | \#285 | `notes.json: rows[4].issue` |
| README defect table | row 5, fix | \#286 | `fixes_by_others[].pr` |
| README defect table | row 6, report | \#7364 | `notes.json: rows[5].issue` |
| README defect table | row 6, fix | \#7467 | `fixes_by_others[].pr` |
| README defect table | row 7, report | \#2443 | `notes.json: rows[6].issue` |
| README defect table | row 7, fix | \#2444 | `fixes_by_others[].pr` |
| README defect table | row 8, report | \#3221 | `notes.json: rows[7].issue` |
| README defect table | row 8, fix | \#3223 | `fixes_by_others[].pr` |
| README fixes table | summary, pull requests | 19 merged pull requests | `len(fixes_by_others) + merged_list entries that close an issue` |
| README fixes table | summary, issues | closed 20 of | `outcomes.fixed_by_merged_pr_from_someone_else + outcomes.fixed_by_his_own_merged_pr` |
| README fixes table | zjunlp/EasyEdit\#717, merged | 09-24 | `fixes_by_others[].merged_at` |
| README fixes table | zjunlp/EasyEdit\#717, hours | 4.7 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | PrairieLearn/PrairieLearn\#15854, merged | 09-25 | `fixes_by_others[].merged_at` |
| README fixes table | PrairieLearn/PrairieLearn\#15854, hours | 26.8 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | ucbds-infra/otter-grader\#1021, merged | 09-25 | `prs.merged_list[].merged_at` |
| README fixes table | ucbds-infra/otter-grader\#1021, hours | 31.1 | `prs.merged_list[].hours` |
| README fixes table | areal-project/AReaL\#1758, merged | 09-27 | `fixes_by_others[].merged_at` |
| README fixes table | areal-project/AReaL\#1758, hours | 56.7 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | datajuicer/data-juicer\#1080, merged | 09-28 | `prs.merged_list[].merged_at` |
| README fixes table | datajuicer/data-juicer\#1080, hours | 101.5 | `prs.merged_list[].hours` |
| README fixes table | modelscope/evalscope\#1785, merged | 09-28 | `fixes_by_others[].merged_at` |
| README fixes table | modelscope/evalscope\#1785, hours | 115.0 / 16.6 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | Marker-Inc-Korea/AutoRAG\#1722, merged | 09-29 | `fixes_by_others[].merged_at` |
| README fixes table | Marker-Inc-Korea/AutoRAG\#1722, hours | 86.7 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | rasbt/mlxtend\#1203, merged | 09-29 | `fixes_by_others[].merged_at` |
| README fixes table | rasbt/mlxtend\#1203, hours | 30.8 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | truera/trulens\#2836, merged | 09-30 | `fixes_by_others[].merged_at` |
| README fixes table | truera/trulens\#2836, hours | 109.5 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | comet-ml/opik\#8528, merged | 09-30 | `fixes_by_others[].merged_at` |
| README fixes table | comet-ml/opik\#8528, hours | 157.7 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | terrierteam/ir\_measures\#84, merged | 09-30 | `prs.merged_list[].merged_at` |
| README fixes table | terrierteam/ir\_measures\#84, hours | 2.5 | `prs.merged_list[].hours` |
| README fixes table | Kaggle/kaggle-benchmarks\#220, merged | 10-01 | `fixes_by_others[].merged_at` |
| README fixes table | Kaggle/kaggle-benchmarks\#220, hours | 187.5 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | Nixtla/statsforecast\#1248, merged | 10-01 | `fixes_by_others[].merged_at` |
| README fixes table | Nixtla/statsforecast\#1248, hours | 27.9 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | Nixtla/utilsforecast\#286, merged | 10-02 | `fixes_by_others[].merged_at` |
| README fixes table | Nixtla/utilsforecast\#286, hours | 105.9 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | EvolvingLMMs-Lab/lmms-eval\#1553, merged | 10-03 | `fixes_by_others[].merged_at` |
| README fixes table | EvolvingLMMs-Lab/lmms-eval\#1553, hours | 235.1 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | huggingface/trl\#7467, merged | 10-06 | `fixes_by_others[].merged_at` |
| README fixes table | huggingface/trl\#7467, hours | 296.2 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | NVIDIA-NeMo/Curator\#2444, merged | 10-07 | `fixes_by_others[].merged_at` |
| README fixes table | NVIDIA-NeMo/Curator\#2444, hours | 316.2 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | scikit-learn-contrib/MAPIE\#994, merged | 10-07 | `fixes_by_others[].merged_at` |
| README fixes table | scikit-learn-contrib/MAPIE\#994, hours | 236.8 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README fixes table | unit8co/darts\#3223, merged | 10-08 | `fixes_by_others[].merged_at` |
| README fixes table | unit8co/darts\#3223, hours | 241.4 | `fixes_by_others[].hours_issue_filed_to_merge` |
| README method | issues total | 238 | `queries.issues_total` |
| README method | issues open | 213 | `queries.issues_open` |
| README method | issues closed | 25 | `queries.issues_closed` |
| README method | prs total | 33 | `queries.prs_total` |
| README method | prs merged | 3 | `queries.prs_merged` |
| README method | prs open | 28 | `queries.prs_open` |
| README method | prs closed unmerged | 2 | `queries.prs_closed_unmerged` |
| README method | PRs to other people's repositories | 33 to other | `prs.upstream` |
| README method | closed issues traced | all 25 closed | `issues.closed` |
| README method | fixed | 20 fixed | `outcomes.fixed_by_merged_pr_from_someone_else + outcomes.fixed_by_his_own_merged_pr` |
| README method | closed without a merged pull request | 5 closed without | `outcomes.closed_not_planned + outcomes.closed_completed_without_a_fix_merged` |
| README method | pull requests by others | 16 pull requests | `fixes_by_others_summary.prs` |
| README method | people | 14 people | `fixes_by_others_summary.distinct_pr_authors` |
| README method | repositories put in areas | 229 repositories | `issues.distinct_repos` |
| README method | areas | 15 areas | `len(ecosystems)` |
| README side quest | panels in the fold | three more panels | `len(PANELS) - 1` |
| README defect table | fixes in the table, lead sentence | eight of the fixes | `len(notes.json rows)` |
| README side quest | lines in the example grader | two-line grader | `len(probe.json source)` |
| README method and footer | as of | 2026-10-08 20:50 utc | `as_of (from fetch.json)` |
| README method | trigalign capture | ds004621 | `trigalign.json source` |
| header | class year | '27 | `WHO.year` |
| header | stops (desc) | nine stops | `len(HEADER_STOPS)` |
| proteins card | residues per turn | 3.6 residues/turn | `360 / PROTEIN.deg` |
| proteins card | rise | 1.5 Å rise | `PROTEIN.rise` |
| proteins card | strand step | 3.3 Å strand step | `PROTEIN.strand_step` |
| proteins card | scale bar | 10 Å | `constant` |
| proteins card | residues (desc) | 41-residue | `len(backbone())` |
| proteins card | helix length (desc) | helix of 18 residues | `PROTEIN.helix` |
| brains card | events paired | 194 of 195 | `trigalign.json logs[0].n_paired, logs[0].n_events` |
| brains card | lost trigger, expected | 638.47 s | `logs[0].unmatched[0].expected_trigger_time` |
| brains card | lost event, log time (desc) | 290.778 s | `logs[0].unmatched[0].time` |
| brains card | triggers lost | one trigger | `logs[0].n_events - logs[0].n_paired` |
| brains card | triggers with no log event | 1 extra trigger | `len(trigalign.json unpaired_triggers)` |
| brains card | residual sd | sd 0.29 ms | `logs[0].segments[0].residual_sd_ms (recomputed from pairs)` |
| brains card | residual max | max 0.54 | `logs[0].segments[0].residual_max_ms (recomputed from pairs)` |
| brains card | drift | -22 ppm | `logs[0].segments[0].drift_ppm` |
| brains card | offset (desc) | 347.7 s | `logs[0].segments[0].offset_s` |
| brains card | residual axis | ±0.6 ms | `ceil(residual_max_ms × 10) / 10` |
| quantum card | E\[BC\]² at 1,024 shots, a lower bound on mean fidelity | 0.9239 | `fidelity_floor(1024) = (√(K/s)·Σ pmf(k;s,1/K)√k)², K=256` |
| quantum card | as the field guide prints it | 0.92 at 1,024 | `round(fidelity_floor(1024), 2)` |
| quantum card | shots for 0.95, by the E\[BC\]² bound | 0.95 needs 1,425 | `shots_for(0.95), bisection` |
| quantum card | E\[BC\]², frame 128 | E\[BC\]² 0.3807 | `fidelity_floor(128)` |
| quantum card | E\[BC\]², frame 256 | E\[BC\]² 0.5986 | `fidelity_floor(256)` |
| quantum card | E\[BC\]², frame 512 | E\[BC\]² 0.8056 | `fidelity_floor(512)` |
| quantum card | E\[BC\]², frame 1,024 | E\[BC\]² 0.9239 | `fidelity_floor(1024)` |
| quantum card | this simulated run | this simulated run 0.9334 | `BC² of splitmix64(0) counts, 1,024 shots, top 8 bits` |
| quantum card | empty outcomes (desc) | 3 outcomes empty | `counts.count(0)` |
| quantum card | outcomes | 256 outcomes | `QUANTUM.K = 2^8, 8 qubits, uniform` |
| quantum card | ideal count per outcome (desc) | ideal of 4 each | `QUANTUM.shots / QUANTUM.K` |
| quantum card | bar clip (desc) | clipped at 4 times the ideal | `QUANTUM.clip` |
| quantum card | frame 128 | 128 shots so far | `QUANTUM.frames` |
| quantum card | frame 256 | 256 shots so far | `QUANTUM.frames` |
| quantum card | frame 512 | 512 shots so far | `QUANTUM.frames` |
| quantum card | seed | seed 0 | `QUANTUM.seed` |
| quantum card | asymptote | 1.0 | `fidelity_floor(s) tends to 1 as s grows` |
| quantum card | axis ends | 64 | `QUANTUM.axis[0]` |
| quantum card | axis ends | 65,536 | `QUANTUM.axis[1]` |
| things i made shelf | tools (desc) | 10 small python tools | `len of every TOOLS group` |
| things i made shelf | headings (desc) | three headings | `len(TOOLS)` |
| side-quest stat tiles, all three widths | since | since 2026-09-23 | `issues.first_created_at` |
| side-quest stat tiles, all three widths | issues filed | 238 issues filed | `issues.total` |
| side-quest stat tiles, all three widths | repositories | 229 repos | `issues.distinct_repos` |
| side-quest stat tiles, all three widths | areas | 15 areas | `len(ecosystems)` |
| side-quest stat tiles, all three widths | fixed | 20 fixed | `fixed (others + own)` |
| side-quest stat tiles, all three widths | fixed by others, by me | 17 by others, 3 by me | `outcomes.fixed_by_merged_pr_from_someone_else, outcomes.fixed_by_his_own_merged_pr` |
| side-quest stat tiles, all three widths | median hours to a fix | median 109.5 hours | `fix_lag_hours_filed_to_merge.median` |
| side-quest stat tiles, all three widths | fixes by others with hours | 17 fixes by others | `fix_lag_hours_filed_to_merge.n` |
| side-quest stat tiles, all three widths | PRs upstream | 33 pull requests to other | `prs.upstream` |
| side-quest stat tiles, all three widths | PRs merged, open | 3 merged, 28 open | `queries.prs_merged, queries.prs_open` |
| divider | dots (desc) | 238 dots | `issues.total` |
| divider | lit (desc) | the 20 fixed | `fixed (others + own)` |
| constellation, all three widths | stars | 238 | `issues.total` |
| constellation, all three widths | lit | fixed by a merged PR: 20 | `fixed (others + own)` |
| constellation, all three widths | fixed by others | fixed by others 17 | `outcomes.fixed_by_merged_pr_from_someone_else` |
| constellation, all three widths | fixed by me | fixed by me 3 | `outcomes.fixed_by_his_own_merged_pr` |
| constellation, all three widths | closed, no fix | closed, no fix 5 | `outcomes.closed_not_planned + outcomes.closed_completed_without_a_fix_merged` |
| constellation, all three widths | open | open 213 | `outcomes.open` |
| constellation, all three widths | repositories | 229 repositories | `issues.distinct_repos` |
| constellation, all three widths | areas | 15 areas | `len(ecosystems)` |
| constellation, all three widths | eval harnesses | eval harnesses 42 | `ecosystems[0].issues` |
| constellation, all three widths | judges &amp; RAG | judges &amp; RAG 29 | `ecosystems[1].issues` |
| constellation, all three widths | RL rewards | RL rewards 22 | `ecosystems[2].issues` |
| constellation, all three widths | agent evals | agent evals 21 | `ecosystems[3].issues` |
| constellation, all three widths | metric libs | metric libs 20 | `ecosystems[4].issues` |
| constellation, all three widths | eval platforms | eval platforms 19 | `ecosystems[5].issues` |
| constellation, all three widths | fairness &amp; UQ | fairness &amp; UQ 18 | `ecosystems[6].issues` |
| constellation, all three widths | code &amp; math | code &amp; math 13 | `ecosystems[7].issues` |
| constellation, all three widths | data pipelines | data pipelines 12 | `ecosystems[8].issues` |
| constellation, all three widths | safety | safety 12 | `ecosystems[9].issues` |
| constellation, all three widths | autograders | autograders 8 | `ecosystems[10].issues` |
| constellation, all three widths | forecasting | forecasting 8 | `ecosystems[11].issues` |
| constellation, all three widths | retrieval | retrieval 7 | `ecosystems[12].issues` |
| constellation, all three widths | explainability | explainability 4 | `ecosystems[13].issues` |
| constellation, all three widths | speech &amp; audio | speech &amp; audio 3 | `ecosystems[14].issues` |
| analyzer, all three widths | filed | 238 filed | `issues.total` |
| analyzer, all three widths | fixed | 20 fixed | `fixed (others + own)` |
| analyzer, all three widths | median wait | median 109.5 h | `fix_lag_hours_filed_to_merge.median, re-derived from created_at to merged_at` |
| analyzer, all three widths | evalscope\#1774 (desc) | evalscope\#1774 115.0 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | lmms-eval\#1546 (desc) | lmms-eval\#1546 235.1 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | kaggle-benchmarks\#217 (desc) | kaggle-benchmarks\#217 187.5 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | Curator\#2443 (desc) | Curator\#2443 316.2 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | opik\#8519 (desc) | opik\#8519 157.7 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | trl\#7364 (desc) | trl\#7364 296.2 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | data-juicer\#1077 (desc) | data-juicer\#1077 101.5 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | EasyEdit\#716 (desc) | EasyEdit\#716 4.7 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | PrairieLearn\#15852 (desc) | PrairieLearn\#15852 26.8 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | otter-grader\#1020 (desc) | otter-grader\#1020 31.1 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | AReaL\#1757 (desc) | AReaL\#1757 56.7 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | trulens\#2823 (desc) | trulens\#2823 109.5 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | AutoRAG\#1707 (desc) | AutoRAG\#1707 86.7 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | evalscope\#1783 (desc) | evalscope\#1783 16.6 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | MAPIE\#993 (desc) | MAPIE\#993 236.8 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | mlxtend\#1202 (desc) | mlxtend\#1202 30.8 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | darts\#3221 (desc) | darts\#3221 241.4 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | utilsforecast\#285 (desc) | utilsforecast\#285 105.9 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | ir\_measures\#83 (desc) | ir\_measures\#83 2.5 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer, all three widths | statsforecast\#1247 (desc) | statsforecast\#1247 27.9 h | `issues.json created_at to the fix's merged_at; equals the fixes table` |
| analyzer (desc) | filed, 09-23 | 09-23 57 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-24 | 09-24 44 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-25 | 09-25 35 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-26 | 09-26 40 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-27 | 09-27 4 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-28 | 09-28 15 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-29 | 09-29 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 09-30 | 09-30 38 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-01 | 10-01 5 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-02 | 10-02 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-03 | 10-03 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-04 | 10-04 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-05 | 10-05 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-06 | 10-06 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-07 | 10-07 0 | `issues.daily_utc[day]` |
| analyzer (desc) | filed, 10-08 | 10-08 0 | `issues.daily_utc[day]` |
| analyzer, all three widths | as of | 10-08 20:50 | `as_of` |

## quoted, not computed

The prose also quotes a few figures from outside data/: the packages' own READMEs, the owner's resume and his personal site. This build cannot recompute them. It checks that each is still on the page, on the line it belongs to, so a figure cannot change on the page without its source being looked at again here.

| where | figure as shown | source |
|:--|:--|:--|
| README field guide, quantum | 8 qubits, uniform target, 1,024 shots: about 0.92 hellinger fidelity | shotfloor README.md, lines 9-20: the example for uniform:8 at 1024 shots prints a hellinger fidelity of 0.9239 |
| things i made shelf and its alt text, normladder | 8 of 14 answer-matching rules | normladder README.md, line 9: the example for "1,000" against "1000" prints 8 of 14 rules match |
| things i made shelf and its alt text, scoreprobe | 4200 against 42 | scoreprobe README.md, lines 4-5: the list of inputs it feeds in |
| README field guide, classrooms | 350+ students | his resume, SkillTern entry (a count he reports himself) |
| README field guide, street safety | 10,000+ LAPD crime datapoints | his resume, TurtleShell entry |
| README field guide, brains | four essays | his personal site, writing page: four neuroscience essays, Feb 2022 to Jul 2023 |

## quoted, not computed (images)

Text the pictures quote rather than compute. Each is checked to be on the picture it names.

| where | figure as shown | source |
|:--|:--|:--|
| header | $ grep -rl "same field" \~/built/ / no matches | his personal site, sessions log |
| music card | $ ls \~/music/released/ / (empty) | his personal site, sessions log |
| brains card | OpenNeuro ds004621 (CC0) | trigalign tests/data/NOTICE |
| brains card | (the recording paused) | trigalign README example output: "on a New Segment marker" |

## drawn by an Action, not recomputed

widgets: not generated yet. The refresh workflow draws them; until it has, the page leaves the commit-weather section out.
