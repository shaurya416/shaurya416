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
| README strip | since | \| since 2026-09-23 \| | `issues.first_created_at` |
| README strip | issues filed | \| 238 \| | `issues.total` |
| README strip | repositories | in 229 repositories | `issues.distinct_repos` |
| README strip | areas | 15 areas | `len(ecosystems)` |
| README strip | fixed | \| 20 \| | `outcomes.fixed_by_merged_pr_from_someone_else + outcomes.fixed_by_his_own_merged_pr` |
| README strip | fixed by others | 17 by other people | `outcomes.fixed_by_merged_pr_from_someone_else` |
| README strip | fixed by own PR | 3 by me | `outcomes.fixed_by_his_own_merged_pr` |
| README strip | median hours | \| 109.5 \| | `fix_lag_hours_filed_to_merge.median` |
| README strip | fixes by others with hours | 17 fixes | `fix_lag_hours_filed_to_merge.n` |
| README strip | PRs upstream | \| 33 \| | `prs.upstream` |
| README strip | PRs merged | 3 merged | `queries.prs_merged` |
| README strip | PRs open | 28 open | `queries.prs_open` |
| README side quest | since | since 2026-09-23: | `issues.first_created_at` |
| README side quest | issues filed | 238 issues in | `issues.total` |
| README side quest | repositories | in 229 repositories | `issues.distinct_repos` |
| README side quest | fixed | 20 fixed by a merged | `outcomes.fixed_by_merged_pr_from_someone_else + outcomes.fixed_by_his_own_merged_pr` |
| README side quest | fixed by others | 17 of those by other people | `outcomes.fixed_by_merged_pr_from_someone_else` |
| README side quest | fixed by own PR | and 3 by me | `outcomes.fixed_by_his_own_merged_pr` |
| README side quest | panels in the fold | three more panels | `len(PANELS) - 1` |
| README defect table | fixes in the table, lead sentence | eight of the fixes | `len(notes.json rows)` |
| README side quest | lines in the example grader | two-line grader | `len(probe.json source)` |
| README method and footer | as of | 2026-10-08 20:50 utc | `as_of (from fetch.json)` |

## quoted, not computed

The prose also quotes a few figures from outside data/: the packages' own READMEs, the owner's resume and his personal site. This build cannot recompute them. It checks that each is still on the page, on the line it belongs to, so a figure cannot change on the page without its source being looked at again here.

| where | figure as shown | source |
|:--|:--|:--|
| README field guide, quantum | 8 qubits, uniform target, 1,024 shots: 0.92 hellinger fidelity | shotfloor README.md, lines 9-20: the example for uniform:8 at 1024 shots prints a hellinger fidelity of 0.9239 |
| README things i made, normladder | 8 of 14 answer-matching rules | normladder README.md, line 9: the example for "1,000" against "1000" prints 8 of 14 rules match |
| README things i made, scoreprobe | 4200 against 42 | scoreprobe README.md, lines 4-5: the list of inputs it feeds in |
| README field guide, classrooms | 350+ students | his resume, SkillTern entry (a count he reports himself) |
| README field guide, street safety | 10,000+ LAPD crime datapoints | his resume, TurtleShell entry |
| README field guide, brains | four essays | his personal site, writing page: four neuroscience essays, Feb 2022 to Jul 2023 |
