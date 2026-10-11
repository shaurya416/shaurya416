**Shaurya Singh** · Seattle, WA · cs + data science at UW, class of '27 · [shauryasingh.com](https://shauryasingh.com)

i find what hurts, then build at it. so far: proteins, brains, quantum noise, classrooms, street safety, buildings, an underwater robot, and the code that grades things.

```
$ grep -rl "same field" ~/built/
no matches
```

### grading the graders

| since 2026-09-23 | | |
|:--|--:|:--|
| issues filed | 238 | in 229 repositories, 15 areas |
| fixed by a merged pull request | 20 | 17 by other people, 3 by me |
| median hours to a fix | 109.5 | filed to merged, over 17 fixes by others |
| pull requests to other people's repositories | 33 | 3 merged, 28 open |

the habit: i read the code that decides whether an answer is right (eval harnesses, classroom autograders, forecasting and fairness metrics) and file what i find. since 2026-09-23: 238 issues in 229 repositories, 20 fixed by a merged pull request so far, 17 of those by other people and 3 by me.

one example, small enough to read: scoreprobe on a two-line grader, before and after a one-line fix.

<p>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/probe-dark.svg?v=f5b5ebe9">
<source media="(prefers-color-scheme: light)" srcset="assets/probe-light.svg?v=9ed7cb48">
<img alt="scoreprobe on a grader that returns reference.lower() in answer.lower(): 5 of 9 checks reproduce, for example &#x27;not Paris&#x27; earns credit against &#x27;Paris&#x27;. With reference.lower() == answer.lower() instead: 0 of 9." src="assets/probe-light.svg?v=9ed7cb48" width="380">
</picture>
</p>

<details>
<summary>three more panels and the one-defect table</summary>

<p>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/filed-dark.svg?v=d5756572">
<source media="(prefers-color-scheme: light)" srcset="assets/filed-light.svg?v=bb60dbcd">
<img alt="Issues filed per day in UTC, 2026-09-23 to 2026-10-08: 57 44 35 40 4 15 0 38 5 0 0 0 0 0 0 0. 238 filed, 20 fixed by a merged PR." src="assets/filed-light.svg?v=bb60dbcd" width="380">
</picture>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/outcome-dark.svg?v=b9cd6d71">
<source media="(prefers-color-scheme: light)" srcset="assets/outcome-light.svg?v=58445d9c">
<img alt="State of each of the 238 issues: fixed by someone else&#x27;s PR 17, by own PR 3, closed without a merged PR 5, open 213. Median 109.5 hours from report to a merged fix by someone else." src="assets/outcome-light.svg?v=58445d9c" width="380">
</picture>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/areas-dark.svg?v=7cba9cd9">
<source media="(prefers-color-scheme: light)" srcset="assets/areas-light.svg?v=47bb114a">
<img alt="238 issues across 229 repositories in 15 areas; largest: eval harnesses &amp; benchmarks, 42." src="assets/areas-light.svg?v=47bb114a" width="380">
</picture>
</p>

eight of the fixes share one defect: a missing, empty or undefined result counted as a score.

<table>
<tr><th align="left" width="25%">report, fixed by</th><th align="left">what was wrong</th></tr>
<tr><td width="25%"><a href="https://github.com/ucbds-infra/otter-grader/issues/1020">otter-grader<wbr>#1020</a><br><sub>shaurya416 <a href="https://github.com/ucbds-infra/otter-grader/pull/1021">#1021</a></sub></td><td>grading produced no results and the log still said all tests passed</td></tr>
<tr><td width="25%"><a href="https://github.com/areal-project/AReaL/issues/1757">AReaL<wbr>#1757</a><br><sub>MohammadHijjawi97 <a href="https://github.com/areal-project/AReaL/pull/1758">#1758</a></sub></td><td>a reply with no answer scored 0.9 against a &quot;None&quot; placeholder gold</td></tr>
<tr><td width="25%"><a href="https://github.com/modelscope/evalscope/issues/1783">evalscope<wbr>#1783</a><br><sub>Yunnglin <a href="https://github.com/modelscope/evalscope/pull/1785">#1785</a></sub></td><td>a blank answer against a blank reference scored full credit</td></tr>
<tr><td width="25%"><a href="https://github.com/rasbt/mlxtend/issues/1202">mlxtend<wbr>#1202</a><br><sub>MohammadHijjawi97 <a href="https://github.com/rasbt/mlxtend/pull/1203">#1203</a></sub></td><td>mcnemar returned p = 0.0 by default when there were no discordant pairs</td></tr>
<tr><td width="25%"><a href="https://github.com/Nixtla/utilsforecast/issues/285">utilsforecast<wbr>#285</a><br><sub>vgvr0 <a href="https://github.com/Nixtla/utilsforecast/pull/286">#286</a></sub></td><td>smape scored a missing forecast as a perfect 0</td></tr>
<tr><td width="25%"><a href="https://github.com/huggingface/trl/issues/7364">trl<wbr>#7364</a><br><sub>adithya-s-k <a href="https://github.com/huggingface/trl/pull/7467">#7467</a></sub></td><td>OpenReward&#x27;s default GRPO reward could not tell never scored from scored 0.0</td></tr>
<tr><td width="25%"><a href="https://github.com/NVIDIA-NeMo/Curator/issues/2443">Curator<wbr>#2443</a><br><sub>1fanwang <a href="https://github.com/NVIDIA-NeMo/Curator/pull/2444">#2444</a></sub></td><td>an empty document scored 1.0 on the repetition filter and was kept</td></tr>
<tr><td width="25%"><a href="https://github.com/unit8co/darts/issues/3221">darts<wbr>#3221</a><br><sub>adigulalkari <a href="https://github.com/unit8co/darts/pull/3223">#3223</a></sub></td><td>grid search returned a NaN-scored combination as the best when it came first in the grid</td></tr>
</table>

</details>

<details>
<summary>19 merged pull requests closed 20 of the issues</summary>

| merged 2026, utc | pull request | by | closes | hours |
|:--|:--|:--|:--|--:|
| 09-24 | [zjunlp/EasyEdit#717](https://github.com/zjunlp/EasyEdit/pull/717) | TengJiao33 | [#716](https://github.com/zjunlp/EasyEdit/issues/716) | 4.7 |
| 09-25 | [PrairieLearn/PrairieLearn#15854](https://github.com/PrairieLearn/PrairieLearn/pull/15854) | jonatanschroeder | [#15852](https://github.com/PrairieLearn/PrairieLearn/issues/15852) | 26.8 |
| 09-25 | [ucbds-infra/otter-grader#1021](https://github.com/ucbds-infra/otter-grader/pull/1021) | shaurya416 | [#1020](https://github.com/ucbds-infra/otter-grader/issues/1020) | 31.1 |
| 09-27 | [areal-project/AReaL#1758](https://github.com/areal-project/AReaL/pull/1758) | MohammadHijjawi97 | [#1757](https://github.com/areal-project/AReaL/issues/1757) | 56.7 |
| 09-28 | [datajuicer/data-juicer#1080](https://github.com/datajuicer/data-juicer/pull/1080) | shaurya416 | [#1077](https://github.com/datajuicer/data-juicer/issues/1077) | 101.5 |
| 09-28 | [modelscope/evalscope#1785](https://github.com/modelscope/evalscope/pull/1785) | Yunnglin | [#1774](https://github.com/modelscope/evalscope/issues/1774), [#1783](https://github.com/modelscope/evalscope/issues/1783) | 115.0 / 16.6 |
| 09-29 | [Marker-Inc-Korea/AutoRAG#1722](https://github.com/Marker-Inc-Korea/AutoRAG/pull/1722) | vkehfdl1 | [#1707](https://github.com/Marker-Inc-Korea/AutoRAG/issues/1707) | 86.7 |
| 09-29 | [rasbt/mlxtend#1203](https://github.com/rasbt/mlxtend/pull/1203) | MohammadHijjawi97 | [#1202](https://github.com/rasbt/mlxtend/issues/1202) | 30.8 |
| 09-30 | [truera/trulens#2836](https://github.com/truera/trulens/pull/2836) | feiiiiii5 | [#2823](https://github.com/truera/trulens/issues/2823) | 109.5 |
| 09-30 | [comet-ml/opik#8528](https://github.com/comet-ml/opik/pull/8528) | desty | [#8519](https://github.com/comet-ml/opik/issues/8519) | 157.7 |
| 09-30 | [terrierteam/ir\_measures#84](https://github.com/terrierteam/ir_measures/pull/84) | shaurya416 | [#83](https://github.com/terrierteam/ir_measures/issues/83) | 2.5 |
| 10-01 | [Kaggle/kaggle-benchmarks#220](https://github.com/Kaggle/kaggle-benchmarks/pull/220) | yyl | [#217](https://github.com/Kaggle/kaggle-benchmarks/issues/217) | 187.5 |
| 10-01 | [Nixtla/statsforecast#1248](https://github.com/Nixtla/statsforecast/pull/1248) | vgvr0 | [#1247](https://github.com/Nixtla/statsforecast/issues/1247) | 27.9 |
| 10-02 | [Nixtla/utilsforecast#286](https://github.com/Nixtla/utilsforecast/pull/286) | vgvr0 | [#285](https://github.com/Nixtla/utilsforecast/issues/285) | 105.9 |
| 10-03 | [EvolvingLMMs-Lab/lmms-eval#1553](https://github.com/EvolvingLMMs-Lab/lmms-eval/pull/1553) | longzhenren | [#1546](https://github.com/EvolvingLMMs-Lab/lmms-eval/issues/1546) | 235.1 |
| 10-06 | [huggingface/trl#7467](https://github.com/huggingface/trl/pull/7467) | adithya-s-k | [#7364](https://github.com/huggingface/trl/issues/7364) | 296.2 |
| 10-07 | [NVIDIA-NeMo/Curator#2444](https://github.com/NVIDIA-NeMo/Curator/pull/2444) | 1fanwang | [#2443](https://github.com/NVIDIA-NeMo/Curator/issues/2443) | 316.2 |
| 10-07 | [scikit-learn-contrib/MAPIE#994](https://github.com/scikit-learn-contrib/MAPIE/pull/994) | SashaMIT | [#993](https://github.com/scikit-learn-contrib/MAPIE/issues/993) | 236.8 |
| 10-08 | [unit8co/darts#3223](https://github.com/unit8co/darts/pull/3223) | adigulalkari | [#3221](https://github.com/unit8co/darts/issues/3221) | 241.4 |

</details>

### field guide

one line per world i've wandered into.

- **proteins** · UW's DAIS lab: preprocessing, training runs and renders for DeepTracer, cryo-EM maps to 3D protein structures. no byline, and that's fine.
- **brains** · four essays, taught to myself in public, optogenetics to connectomics (2022–23). now **trigalign**, for EEG recordings that dropped a trigger or two.
- **quantum** · **shotfloor**: the score a perfect quantum computer gets from shot noise alone. 8 qubits, uniform target, 1,024 shots: 0.92 hellinger fidelity, not 1.
- **classrooms** · co-founded SkillTern, its CTO (2022–23): computer science for 350+ students, built to run without me.
- **street safety** · TurtleShell: K-means over 10,000+ LAPD crime datapoints and an iOS SOS app. Microsoft for Startups, then shut down on purpose (oct 2023).
- **buildings** · a cabin designer that has to pass the Seattle residential code: rule engine, NSGA-II over cost, space and comfort, IFC export. runs locally, so no link.
- **earlier** · H2OAquatics, an autonomous underwater vehicle aimed at ocean acidification; a phishing policy paper, runner-up at WatGov (Waterloo, 2023).
- **off the clock** · music. made often, released never.

### things i made

small python tools, each about one thing that quietly goes wrong. none is public yet, so no links: each name becomes one the day its repository is.

| | | |
|:--|:--|:--|
| tests and repos | **tolwatch** | pytest plugin: flags `allclose`, `isclose` and `approx` checks that can't fail, or are far looser than they need to be |
|  | **ziptrace** | names the `zip()` and `map()` calls that silently dropped data to a length mismatch |
|  | **unadded** | finds the untracked or gitignored files a passing test run quietly depends on, before CI does |
|  | **whymodified** | `git status` says modified and nothing changed: says why, and the one command that clears it |
| science data | **shotfloor** | the score a flawless quantum computer gets at a given shot count, and the shots it needs to reach a target |
|  | **trigalign** | pairs a stimulus log with an EEG trigger list when triggers dropped, doubled, or the clocks drifted |
| grading code | **scoreprobe** | feeds a grader the inputs known to slip through (a blank answer, "not Paris" against "Paris", 4200 against 42) and reports which earned credit |
|  | **normladder** | is "1,000" the same answer as "1000"? 8 of 14 answer-matching rules from lm-eval, HELM and SQuAD say yes; it shows which, and why |
|  | **mcqlint** | lints multiple-choice eval sets: keys that name no option, duplicate options, leaked answers, position bias |
|  | **tabverify** | recomputes the averages, deltas and bold in results tables at the printed precision, and flags what no rounding explains |

<details>
<summary>method</summary>

- counts are `total_count` from GitHub search at 2026-10-08 20:50 utc: `author:shaurya416 is:public is:issue` (238: 213 open, 25 closed) and `author:shaurya416 is:public is:pr` (33: 3 merged, 28 open, 2 closed unmerged; 33 to other people's repositories), excluding the owner's own organisations.
- fixed means the issue is closed and a pull request in its repository that references it was merged before it closed; an issue closed as not planned never counts. all 25 closed issues were traced: 20 fixed, 5 closed without a merged pull request. the 16 pull requests by others come from 14 people.
- an open issue whose fix did not close it is not counted, so fixed is a lower bound.
- hours run from the issue being filed to the pull request merging.
- areas: each of the 229 repositories is put in one of 15 areas by hand. that, the four kinds of code the side-quest sentence names, the sentence above the defect table and its one line per row are the hand-written inputs to the side quest.
- the scoreprobe panel is a captured run of scoreprobe on the code it shows. its first public release is pending; with its source, `python3 build.py capture-probe --scoreprobe-src PATH` reruns the panel.
- days are utc. a day with nothing is drawn as a mark, not left blank.
- regenerate: `python3 build.py fetch` reads the api (it needs `GITHUB_TOKEN`), then `python3 build.py` renders. same input, same bytes.

</details>

<sub>side-quest numbers: github api, as of 2026-10-08 20:50 utc.</sub>
