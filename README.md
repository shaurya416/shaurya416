<p>
<picture>
<source media="(max-width: 600px) and (prefers-color-scheme: dark), (min-width: 768px) and (max-width: 859px) and (prefers-color-scheme: dark)" srcset="assets/header-narrow-dark.svg?v=b4fccf4c">
<source media="(max-width: 600px), (min-width: 768px) and (max-width: 859px)" srcset="assets/header-narrow-light.svg?v=d0649848">
<source media="(min-width: 601px) and (max-width: 767px) and (prefers-color-scheme: dark), (min-width: 860px) and (max-width: 1199px) and (prefers-color-scheme: dark)" srcset="assets/header-mid-dark.svg?v=e1f5626a">
<source media="(min-width: 601px) and (max-width: 767px), (min-width: 860px) and (max-width: 1199px)" srcset="assets/header-mid-light.svg?v=04d0a787">
<source media="(prefers-color-scheme: dark)" srcset="assets/header-dark.svg?v=9d9e1f94">
<img alt="Shaurya Singh, Seattle, cs at UW, class of &#x27;27. A route through eight stops, drawn as icons: brains, quantum, classrooms, street safety, buildings, underwater robot, graders, music. A terminal: $ grep -rl &quot;same field&quot; ~/built/ prints no matches." src="assets/header-light.svg?v=566f2f9a" width="100%">
</picture>
</p>

[shauryasingh.com](https://shauryasingh.com)

i find what hurts, then build at it. so far: brains, quantum noise, classrooms, street safety, buildings, an underwater robot, and the code that grades things.

### grading the graders

the habit: i read the code that decides whether an answer is right (eval harnesses, classroom autograders, forecasting and fairness metrics) and file what i find.

<p>
<picture>
<source media="(max-width: 600px) and (prefers-color-scheme: dark), (min-width: 768px) and (max-width: 859px) and (prefers-color-scheme: dark)" srcset="assets/stats-narrow-dark.svg?v=b1efb140">
<source media="(max-width: 600px), (min-width: 768px) and (max-width: 859px)" srcset="assets/stats-narrow-light.svg?v=94dc3c32">
<source media="(min-width: 601px) and (max-width: 767px) and (prefers-color-scheme: dark), (min-width: 860px) and (max-width: 1199px) and (prefers-color-scheme: dark)" srcset="assets/stats-mid-dark.svg?v=1c76ce2d">
<source media="(min-width: 601px) and (max-width: 767px), (min-width: 860px) and (max-width: 1199px)" srcset="assets/stats-mid-light.svg?v=45924520">
<source media="(prefers-color-scheme: dark)" srcset="assets/stats-dark.svg?v=51f977f3">
<img alt="Since 2026-09-23: 238 issues filed in 229 repositories, 15 areas; 30 fixed by a merged pull request, 27 by other people and 3 by me; median 236.8 hours from filing to the merged pull request, over 27 fixes by others; 32 pull requests to other people&#x27;s repositories, 3 merged and 25 open." src="assets/stats-light.svg?v=85c52ac4" width="100%">
</picture>
</p>

<p>
<picture>
<source media="(max-width: 600px) and (prefers-color-scheme: dark), (min-width: 768px) and (max-width: 859px) and (prefers-color-scheme: dark)" srcset="assets/constellation-narrow-dark.svg?v=4e598d6d">
<source media="(max-width: 600px), (min-width: 768px) and (max-width: 859px)" srcset="assets/constellation-narrow-light.svg?v=24a6a278">
<source media="(min-width: 601px) and (max-width: 767px) and (prefers-color-scheme: dark), (min-width: 860px) and (max-width: 1199px) and (prefers-color-scheme: dark)" srcset="assets/constellation-mid-dark.svg?v=5c0b6c0f">
<source media="(min-width: 601px) and (max-width: 767px), (min-width: 860px) and (max-width: 1199px)" srcset="assets/constellation-mid-light.svg?v=d72343a0">
<source media="(prefers-color-scheme: dark)" srcset="assets/constellation-dark.svg?v=2859f5af">
<img alt="238 issues drawn as stars in 15 clusters, one per area: eval harnesses 42, judges &amp; RAG 29, RL rewards 22, agent evals 21, metric libs 20, eval platforms 19, fairness &amp; UQ 18, code &amp; math 13, data pipelines 12, safety 12, autograders 8, forecasting 8, retrieval 7, explainability 4, speech &amp; audio 3. Lit: 30 fixed by a merged pull request, 27 by other people and 3 by me (ringed). Rings: 9 closed without a fix. Dots: 199 open. 229 repositories in 15 areas." src="assets/constellation-light.svg?v=47ffe98b" width="100%">
</picture>
</p>

one example, small enough to read: scoreprobe on a two-line grader, before and after a one-line fix.

<p align="center">
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/probe-dark.svg?v=f5b5ebe9">
<source media="(prefers-color-scheme: light)" srcset="assets/probe-light.svg?v=9ed7cb48">
<img alt="scoreprobe on a grader that returns reference.lower() in answer.lower(): 5 of 9 checks reproduce, for example &#x27;not Paris&#x27; earns credit against &#x27;Paris&#x27;. With reference.lower() == answer.lower() instead: 0 of 9." src="assets/probe-light.svg?v=9ed7cb48" width="380">
</picture>
</p>

<details>
<summary>three more panels and the one-defect table</summary>

<p align="center">
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/filed-dark.svg?v=f777d9f4">
<source media="(prefers-color-scheme: light)" srcset="assets/filed-light.svg?v=99811fe4">
<img alt="Issues filed per week in UTC, 2026-09-23 to 2026-11-07: 180 58 0 0 0 0 0. 238 filed, 30 fixed by a merged PR." src="assets/filed-light.svg?v=99811fe4" width="380">
</picture>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/outcome-dark.svg?v=a11727cf">
<source media="(prefers-color-scheme: light)" srcset="assets/outcome-light.svg?v=4e6fcb18">
<img alt="State of each of the 238 issues: fixed by someone else&#x27;s PR 27, by own PR 3, closed without a merged PR 9, open 199. Median 236.8 hours from report to a merged fix by someone else." src="assets/outcome-light.svg?v=4e6fcb18" width="380">
</picture>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/areas-dark.svg?v=0fdc2a5a">
<source media="(prefers-color-scheme: light)" srcset="assets/areas-light.svg?v=f56dc0bf">
<img alt="238 issues across 229 repositories in 15 areas; largest: eval harnesses &amp; benchmarks, 42." src="assets/areas-light.svg?v=f56dc0bf" width="380">
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
<summary>29 merged pull requests closed 30 of the issues</summary>

<p>
<picture>
<source media="(max-width: 600px) and (prefers-color-scheme: dark), (min-width: 768px) and (max-width: 859px) and (prefers-color-scheme: dark)" srcset="assets/analyzer-narrow-dark.svg?v=64866de6">
<source media="(max-width: 600px), (min-width: 768px) and (max-width: 859px)" srcset="assets/analyzer-narrow-light.svg?v=a864b3c1">
<source media="(min-width: 601px) and (max-width: 767px) and (prefers-color-scheme: dark), (min-width: 860px) and (max-width: 1199px) and (prefers-color-scheme: dark)" srcset="assets/analyzer-mid-dark.svg?v=82c834d8">
<source media="(min-width: 601px) and (max-width: 767px), (min-width: 860px) and (max-width: 1199px)" srcset="assets/analyzer-mid-light.svg?v=8349f582">
<source media="(prefers-color-scheme: dark)" srcset="assets/analyzer-dark.svg?v=bf99a091">
<img alt="Report to fix, drawn as a logic analyzer. Top channel: one edge per issue filed, 238 in all; filed per week: week of 09-21 180, week of 09-28 58, week of 10-05 0, week of 10-12 0, week of 10-19 0, week of 10-26 0, week of 11-02 0. Below, one channel per fixed issue (30), high from the report until the merged pull request that closed it: promptfoo#11041 360.5 h, giskard-oss#2840 834.5 h, evalscope#1774 115.0 h, lmms-eval#1546 235.1 h, OSWorld#597 614.5 h, kaggle-benchmarks#217 187.5 h, Curator#2443 316.2 h, opik#8519 157.7 h, trl#7364 296.2 h, data-juicer#1077 101.5 h, EasyEdit#716 4.7 h, PrairieLearn#15852 26.8 h, otter-grader#1020 31.1 h, AReaL#1757 56.7 h, trulens#2823 109.5 h, agenta#7149 316.2 h, AutoRAG#1707 86.7 h, agentic_security#350 541.1 h, ai-gateway#447 532.8 h, verifywise#4783 776.5 h, evalscope#1783 16.6 h, MAPIE#993 236.8 h, mlxtend#1202 30.8 h, shapash#777 245.8 h, darts#3221 241.4 h, utilsforecast#285 105.9 h, aeon#3880 341.9 h, ir_measures#83 2.5 h, statsforecast#1247 27.9 h, rouge#77 780.9 h. Three are mine: data-juicer#1077 101.5 h, otter-grader#1020 31.1 h, ir_measures#83 2.5 h. Median wait for fixes by others: 236.8 h. As of 11-07 12:57 utc." src="assets/analyzer-light.svg?v=0cf77dc8" width="100%">
</picture>
</p>

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
| 10-08 | [promptfoo/promptfoo#11445](https://github.com/promptfoo/promptfoo/pull/11445) | he-yufeng | [#11041](https://github.com/promptfoo/promptfoo/issues/11041) | 360.5 |
| 10-08 | [unit8co/darts#3223](https://github.com/unit8co/darts/pull/3223) | adigulalkari | [#3221](https://github.com/unit8co/darts/issues/3221) | 241.4 |
| 10-08 | [MAIF/shapash#794](https://github.com/MAIF/shapash/pull/794) | aminemanai2003 | [#777](https://github.com/MAIF/shapash/issues/777) | 245.8 |
| 10-08 | [Agenta-AI/agenta#7161](https://github.com/Agenta-AI/agenta/pull/7161) | unfitcoder101 | [#7149](https://github.com/Agenta-AI/agenta/issues/7149) | 316.2 |
| 10-12 | [aeon-toolkit/aeon#3887](https://github.com/aeon-toolkit/aeon/pull/3887) | anshuman83-40 | [#3880](https://github.com/aeon-toolkit/aeon/issues/3880) | 341.9 |
| 10-18 | [ferro-labs/ai-gateway#455](https://github.com/ferro-labs/ai-gateway/pull/455) | MitulShah1 | [#447](https://github.com/ferro-labs/ai-gateway/issues/447) | 532.8 |
| 10-18 | [msoedov/agentic\_security#352](https://github.com/msoedov/agentic_security/pull/352) | msoedov | [#350](https://github.com/msoedov/agentic_security/issues/350) | 541.1 |
| 10-19 | [xlang-ai/OSWorld#614](https://github.com/xlang-ai/OSWorld/pull/614) | Timothyxxx | [#597](https://github.com/xlang-ai/OSWorld/issues/597) | 614.5 |
| 10-28 | [Giskard-AI/giskard-oss#2904](https://github.com/Giskard-AI/giskard-oss/pull/2904) | kevinmessiaen | [#2840](https://github.com/Giskard-AI/giskard-oss/issues/2840) | 834.5 |
| 10-28 | [verifywise-ai/verifywise#5147](https://github.com/verifywise-ai/verifywise/pull/5147) | MuhammadKhalilzadeh | [#4783](https://github.com/verifywise-ai/verifywise/issues/4783) | 776.5 |
| 11-02 | [pltrdy/rouge#78](https://github.com/pltrdy/rouge/pull/78) | DataDetective-Neel | [#77](https://github.com/pltrdy/rouge/issues/77) | 780.9 |

</details>

<p>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/divider-dark.svg?v=9f34a0e0">
<source media="(prefers-color-scheme: light)" srcset="assets/divider-light.svg?v=b8e1ff95">
<img alt="238 dots, one per issue in the order filed; the 30 fixed by a merged pull request are lit." src="assets/divider-light.svg?v=b8e1ff95" width="100%">
</picture>
</p>

### field guide

<p align="center">
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/quantum-dark.svg?v=507063c8">
<source media="(prefers-color-scheme: light)" srcset="assets/quantum-light.svg?v=41bc3485">
<img alt="A flawless 8-qubit device sampling a uniform target: one simulated run of 1,024 shots (splitmix64, seed 0) as 256 bars against the ideal of 4 each, bars clipped at 4 times the ideal. This run scores 0.9334 and leaves 3 outcomes empty. The curve is shotfloor&#x27;s closed form E&#91;BC&#93;², a lower bound on the mean Hellinger fidelity: 0.3807, 0.5986, 0.8056 at 128, 256, 512 shots; 0.9239 at 1,024 shots (0.92 at 1,024 on the curve); by that bound, shotfloor puts 0.95 at 1,425 shots; 1.0 only at infinite shots. The curve runs from 64 to 65,536 shots." src="assets/quantum-light.svg?v=41bc3485" width="380">
</picture>
</p>

one line per world i've wandered into.

- **brains** · four essays, taught to myself in public, optogenetics to connectomics (2022–23).
- **quantum** · **shotfloor**: the score a perfect quantum computer gets from shot noise alone. 8 qubits, uniform target, 1,024 shots: about 0.92 hellinger fidelity, not 1.
- **classrooms** · co-founded SkillTern, its CTO (2022–23): computer science for 350+ students, built to run without me.
- **street safety** · TurtleShell: K-means over 10,000+ LAPD crime datapoints and an iOS SOS app in Swift. Microsoft for Startups, then shut down on purpose (oct 2023).
- **buildings** · a cabin designer that has to pass the Seattle residential code: rule engine, NSGA-II over cost, space and comfort, IFC export. runs locally, so no link.
- **earlier** · H2OAquatics, an autonomous underwater vehicle aimed at ocean acidification; a co-written policy paper on phishing, runner-up at WatGov (Waterloo, 2023).
- **off the clock** · music. made often, released never.

<p>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/divider-dark.svg?v=9f34a0e0">
<source media="(prefers-color-scheme: light)" srcset="assets/divider-light.svg?v=b8e1ff95">
<img alt="238 dots, one per issue in the order filed; the 30 fixed by a merged pull request are lit." src="assets/divider-light.svg?v=b8e1ff95" width="100%">
</picture>
</p>

### things i made

small python tools, each about one thing that quietly goes wrong. none is public yet, so no links: each name becomes one the day its repository is.

<p>
<picture>
<source media="(max-width: 600px) and (prefers-color-scheme: dark), (min-width: 768px) and (max-width: 859px) and (prefers-color-scheme: dark)" srcset="assets/shelf-narrow-dark.svg?v=61c16282">
<source media="(max-width: 600px), (min-width: 768px) and (max-width: 859px)" srcset="assets/shelf-narrow-light.svg?v=f01aee79">
<source media="(min-width: 601px) and (max-width: 767px) and (prefers-color-scheme: dark), (min-width: 860px) and (max-width: 1199px) and (prefers-color-scheme: dark)" srcset="assets/shelf-mid-dark.svg?v=79077fc5">
<source media="(min-width: 601px) and (max-width: 767px), (min-width: 860px) and (max-width: 1199px)" srcset="assets/shelf-mid-light.svg?v=ee86b2fb">
<source media="(prefers-color-scheme: dark)" srcset="assets/shelf-dark.svg?v=0a501558">
<img alt="8 small python tools as cards on a shelf, each with an icon, under three headings. tests and repos: tolwatch, pytest plugin: flags allclose, isclose and approx checks that can&#x27;t fail, or are far looser than they need to be; ziptrace, names the zip() and map() calls that silently dropped data to a length mismatch; whymodified, git status says modified and nothing changed: says why, and the one command that clears it. science data: shotfloor, the score a flawless quantum computer gets at a given shot count, and the shots it needs to reach a target. grading code: scoreprobe, feeds a grader the inputs known to slip through (a blank answer, &quot;not Paris&quot; against &quot;Paris&quot;, 4200 against 42) and reports which earned credit; normladder, is &quot;1,000&quot; the same answer as &quot;1000&quot;? 8 of 14 answer-matching rules from lm-eval, HELM and SQuAD say yes; it shows which, and why; mcqlint, lints multiple-choice eval sets: keys that name no option, duplicate options, leaked answers, position bias; tabverify, recomputes the averages, deltas and bold in results tables at the printed precision, and flags what no rounding explains." src="assets/shelf-light.svg?v=33740d87" width="100%">
</picture>
</p>

### commit weather

<p>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="profile-3d-contrib/3d-dark.svg?v=00a41cd0">
<source media="(prefers-color-scheme: light)" srcset="profile-3d-contrib/3d-light.svg?v=61c1c665">
<img alt="A 3D contribution calendar for the past year, drawn by a GitHub Action from the public profile calendar, with a radar of commits, issues, pull requests, reviews and repositories and a language chart. On a phone it is a picture of the calendar&#x27;s shape; its small labels are not meant to be read there. Its totals are the calendar&#x27;s own." src="profile-3d-contrib/3d-light.svg?v=61c1c665" width="100%">
</picture>
</p>
<p>
<picture>
<source media="(prefers-color-scheme: dark)" srcset="assets/contrib/snake-dark.svg?v=bb289d25">
<source media="(prefers-color-scheme: light)" srcset="assets/contrib/snake-light.svg?v=5638c6f7">
<img alt="A snake eats the public profile calendar of the past year, once, and leaves the grid as it found it." src="assets/contrib/snake-light.svg?v=5638c6f7" width="100%">
</picture>
</p>

<sub>drawn daily by two GitHub Actions from the public profile calendar: the shape of the year, not numbers to read. the totals in the 3D picture are the calendar's own.</sub>

<details>
<summary>method</summary>

- counts are `total_count` from GitHub search at 2026-11-07 12:57 utc: `author:shaurya416 is:public is:issue` (238: 199 open, 39 closed) and `author:shaurya416 is:public is:pr` (32: 3 merged, 25 open, 4 closed unmerged; 32 to other people's repositories), excluding the owner's own organisations.
- fixed means the issue is closed and a pull request in its repository that references it was merged before it closed; an issue closed as not planned never counts. all 39 closed issues were traced: 30 fixed, 9 closed without a merged pull request. the 26 pull requests by others come from 24 people.
- an open issue whose fix did not close it is not counted, so fixed is a lower bound.
- hours run from the issue being filed to the pull request merging.
- areas: each of the 229 repositories is put in one of 15 areas by hand. that, the four kinds of code the side-quest sentence names, the sentence above the defect table and its one line per row are the hand-written inputs to the side quest.
- the scoreprobe panel is a captured run of scoreprobe on the code it shows. its first public release is pending; with its source, `python3 build.py capture-probe --scoreprobe-src PATH` reruns the panel.
- weeks start on monday, utc. a week with nothing is drawn as a mark, not left blank.
- regenerate (python 3.12 or newer): `python3 build.py fetch` reads the api (it needs `GITHUB_TOKEN`), then `python3 build.py` renders. same input, same bytes.
- the quantum card is computed, not measured: the curve is shotfloor's closed form E[BC]², a lower bound on the mean hellinger fidelity, and the bars one simulated flawless run (splitmix64, seed 0).
- the header's and the shelf's icons are icons.
- the constellation, divider and report-to-fix pictures are drawn from the same data as the tables, and every number on them is in CHECKS.md.
- the 3D graph and the snake are drawn by two GitHub Actions pinned to full commit SHAs, from the public profile calendar; their totals are the calendar's.

</details>

<sub>side-quest numbers: github api, as of 2026-11-07 12:57 utc.</sub>
