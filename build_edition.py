#!/usr/bin/env python3
"""Print today's edition of The Model Desk into docs/editions/.

Runs on a schedule. It skips quietly if it's before BUILD_HOUR local time or if
today's edition already exists. Pass --force to rebuild today's edition anyway.
"""
import concurrent.futures as cf
import datetime
import json
import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

TZ = ZoneInfo(os.environ.get("TIMEZONE") or "America/New_York")
MODEL = os.environ.get("MODEL") or "claude-sonnet-5-5"
BUILD_HOUR = int(os.environ.get("BUILD_HOUR") or 6)
DEEPER = (os.environ.get("DEEPER") or "1") != "0"
EDITIONS = Path(__file__).parent / "docs" / "editions"

# Each section is one dict. To add a section, add an entry here; the site and the email pick it up automatically.
#   days:      how far back to search for news
#   focus:     optional list of topics; one is chosen per day (rotating) for the first story
#   backstory: write the history and background of the problem before the news itself
#   fact_check: run a second pass with web search that verifies every specific claim
SECTIONS = [
    {"id": "architectures", "name": "Architectures", "brief": "new model architectures and components: attention variants, mixture-of-experts, state-space and hybrid models, long-context methods, multimodal designs, tokenization"},
    {"id": "training", "name": "Training", "brief": "pretraining recipes, data curation, synthetic data, post-training and reinforcement learning (RLHF, DPO, GRPO, RL from verifiable rewards), distillation, optimizers"},
    {"id": "theory", "name": "Theory", "brief": "mathematical and scientific understanding: scaling laws, optimization theory, interpretability (sparse autoencoders, circuits), generalization, evaluation methodology"},
    {"id": "practice", "name": "In Practice", "brief": "deployment and real-world use: inference efficiency (quantization, speculative decoding, KV cache, serving systems), model releases and APIs, agents and tool use in production, costs, open-weight versus closed models"},
    {"id": "robotics", "name": "Robotics", "brief": "embodied AI: vision-language-action models, robot foundation models, world models, sim-to-real transfer, learning from demonstration, humanoids"},
    {"id": "discoveries", "name": "Discoveries", "days": 30, "backstory": True, "fact_check": True,
     "brief": "major scientific advances made with AI: theorems proved or disproved by AI systems (including results from OpenAI, Anthropic, Google DeepMind, and academic groups), protein structure and design, biology and medicine, chemistry and materials, physics and weather",
     "focus": ["mathematics: theorems and open problems resolved with AI", "protein folding, structure prediction, and protein design",
               "mathematics: formal verification and proof assistants such as Lean", "biology, genomics, and medicine",
               "chemistry and materials discovery", "physics, climate, and weather modeling"]},
]
PRIMERS = [
    "The transformer revisited: attention as a soft dictionary lookup", "Tokenization and byte-pair encoding",
    "Positional encodings: from sinusoids to RoPE", "Scaling laws: from Kaplan to Chinchilla",
    "FlashAttention and IO-aware kernels", "The KV cache and why decoding is memory-bound",
    "Grouped-query and multi-head latent attention", "Mixture-of-experts routing and load balancing",
    "Instruction tuning and supervised fine-tuning", "RLHF: reward models and PPO",
    "Direct Preference Optimization", "GRPO and reinforcement learning from verifiable rewards",
    "Reasoning models and test-time compute", "LoRA and parameter-efficient fine-tuning",
    "Quantization: from INT8 to 4-bit and below", "Speculative decoding",
    "Extending context length and its limits", "State-space models and Mamba",
    "Hybrid attention and state-space architectures", "Knowledge distillation for large models",
    "Synthetic data and data curation", "Retrieval-augmented generation",
    "Tool use and function calling", "Agents: planning loops and scaffolds",
    "Vision transformers and contrastive pretraining (CLIP)", "Vision-language models",
    "Diffusion models: score matching and DDPM", "Flow matching and rectified flow",
    "Diffusion transformers", "Video generation and learned world models",
    "Vision-language-action models", "Diffusion policies for robot control",
    "Mechanistic interpretability and circuits", "Sparse autoencoders and learned features",
    "Evaluation: benchmarks, contamination, and evals", "Optimizers: AdamW, Lion, and Muon",
    "Parallelism at scale: data, tensor, pipeline, expert", "Constitutional AI and safety training",
    "Multi-token prediction", "Serving: continuous batching and PagedAttention",
]

# Throwback topics with curated citations. The model may cite only these, so names, venues, and years come
# from this list rather than from the model's memory. "notes" holds extra verified details it may use.
def _ax(i): return f"https://arxiv.org/abs/{i}"
THROWBACKS = [
    {"topic": "Hopfield networks and associative memory", "era": "1982", "papers": [
        ("Hopfield, J. J. (1982). Neural networks and physical systems with emergent collective computational abilities. PNAS.", "")]},
    {"topic": "Backpropagation", "era": "1986", "papers": [
        ("Rumelhart, D. E., Hinton, G. E., & Williams, R. J. (1986). Learning representations by back-propagating errors. Nature.", "https://www.nature.com/articles/323533a0")]},
    {"topic": "Convolutional networks and LeNet", "era": "1989 to 1998", "papers": [
        ("LeCun, Y., et al. (1989). Backpropagation applied to handwritten zip code recognition. Neural Computation.", ""),
        ("LeCun, Y., Bottou, L., Bengio, Y., & Haffner, P. (1998). Gradient-based learning applied to document recognition. Proceedings of the IEEE.", "")]},
    {"topic": "Universal approximation", "era": "1989", "papers": [
        ("Cybenko, G. (1989). Approximation by superpositions of a sigmoidal function. Mathematics of Control, Signals and Systems.", ""),
        ("Hornik, K., Stinchcombe, M., & White, H. (1989). Multilayer feedforward networks are universal approximators. Neural Networks.", "")]},
    {"topic": "Mixture of experts, the original idea", "era": "1991, revived 2017", "papers": [
        ("Jacobs, R. A., Jordan, M. I., Nowlan, S. J., & Hinton, G. E. (1991). Adaptive mixtures of local experts. Neural Computation.", ""),
        ("Shazeer, N., et al. (2017). Outrageously large neural networks: The sparsely-gated mixture-of-experts layer. ICLR 2017.", _ax("1701.06538"))]},
    {"topic": "Long short-term memory", "era": "1997 to 2000", "papers": [
        ("Hochreiter, S., & Schmidhuber, J. (1997). Long short-term memory. Neural Computation.", ""),
        ("Gers, F. A., Schmidhuber, J., & Cummins, F. (2000). Learning to forget: Continual prediction with LSTM. Neural Computation.", "")],
     "notes": "The original 1997 LSTM had no forget gate; Gers, Schmidhuber, and Cummins (2000) added it."},
    {"topic": "Deep belief networks and the 2006 revival", "era": "2006", "papers": [
        ("Hinton, G. E., Osindero, S., & Teh, Y.-W. (2006). A fast learning algorithm for deep belief nets. Neural Computation.", ""),
        ("Hinton, G. E., & Salakhutdinov, R. R. (2006). Reducing the dimensionality of data with neural networks. Science.", "")]},
    {"topic": "Weight initialization: Glorot and He", "era": "2010 to 2015", "papers": [
        ("Glorot, X., & Bengio, Y. (2010). Understanding the difficulty of training deep feedforward neural networks. AISTATS 2010.", ""),
        ("He, K., Zhang, X., Ren, S., & Sun, J. (2015). Delving deep into rectifiers: Surpassing human-level performance on ImageNet classification. ICCV 2015.", _ax("1502.01852"))]},
    {"topic": "AlexNet and the ImageNet moment", "era": "2012", "papers": [
        ("Krizhevsky, A., Sutskever, I., & Hinton, G. E. (2012). ImageNet classification with deep convolutional neural networks. NeurIPS 2012.", ""),
        ("Hinton, G. E., et al. (2012). Improving neural networks by preventing co-adaptation of feature detectors. arXiv.", _ax("1207.0580"))],
     "notes": "AlexNet used ReLU activations, dropout in the fully connected layers, and training split across two GPUs. Its ILSVRC-2012 top-5 test error was 15.3%, versus 26.2% for the second-best entry."},
    {"topic": "word2vec and distributed word representations", "era": "2013", "papers": [
        ("Mikolov, T., Chen, K., Corrado, G., & Dean, J. (2013). Efficient estimation of word representations in vector space. arXiv.", _ax("1301.3781")),
        ("Mikolov, T., et al. (2013). Distributed representations of words and phrases and their compositionality. NeurIPS 2013.", _ax("1310.4546"))]},
    {"topic": "Variational autoencoders", "era": "2013 to 2014", "papers": [
        ("Kingma, D. P., & Welling, M. (2013). Auto-encoding variational Bayes. ICLR 2014.", _ax("1312.6114")),
        ("Rezende, D. J., Mohamed, S., & Wierstra, D. (2014). Stochastic backpropagation and approximate inference in deep generative models. ICML 2014.", _ax("1401.4082"))]},
    {"topic": "Deep Q-networks", "era": "2013 to 2015", "papers": [
        ("Mnih, V., et al. (2013). Playing Atari with deep reinforcement learning. arXiv.", _ax("1312.5602")),
        ("Mnih, V., et al. (2015). Human-level control through deep reinforcement learning. Nature.", "")]},
    {"topic": "Generative adversarial networks", "era": "2014", "papers": [
        ("Goodfellow, I., et al. (2014). Generative adversarial nets. NeurIPS 2014.", _ax("1406.2661"))]},
    {"topic": "Sequence-to-sequence learning", "era": "2014", "papers": [
        ("Cho, K., et al. (2014). Learning phrase representations using RNN encoder-decoder for statistical machine translation. EMNLP 2014.", _ax("1406.1078")),
        ("Sutskever, I., Vinyals, O., & Le, Q. V. (2014). Sequence to sequence learning with neural networks. NeurIPS 2014.", _ax("1409.3215"))]},
    {"topic": "Attention for alignment: Bahdanau and Luong", "era": "2014 to 2015", "papers": [
        ("Bahdanau, D., Cho, K., & Bengio, Y. (2014). Neural machine translation by jointly learning to align and translate. ICLR 2015.", _ax("1409.0473")),
        ("Xu, K., et al. (2015). Show, attend and tell: Neural image caption generation with visual attention. ICML 2015.", _ax("1502.03044")),
        ("Luong, M.-T., Pham, H., & Manning, C. D. (2015). Effective approaches to attention-based neural machine translation. EMNLP 2015.", _ax("1508.04025"))],
     "notes": "Bahdanau attention is additive: e_ij = v^T tanh(W s_{i-1} + U h_j). Luong et al. proposed dot, general (bilinear), and concat scores, and global versus local attention."},
    {"topic": "Adam and adaptive optimizers", "era": "2011 to 2014", "papers": [
        ("Duchi, J., Hazan, E., & Singer, Y. (2011). Adaptive subgradient methods for online learning and stochastic optimization. JMLR.", ""),
        ("Kingma, D. P., & Ba, J. (2014). Adam: A method for stochastic optimization. ICLR 2015.", _ax("1412.6980"))],
     "notes": "RMSProp was introduced in Geoffrey Hinton's Coursera lecture slides (2012), not in a paper."},
    {"topic": "Batch normalization and layer normalization", "era": "2015 to 2016", "papers": [
        ("Ioffe, S., & Szegedy, C. (2015). Batch normalization: Accelerating deep network training by reducing internal covariate shift. ICML 2015.", _ax("1502.03167")),
        ("Ba, J. L., Kiros, J. R., & Hinton, G. E. (2016). Layer normalization. arXiv.", _ax("1607.06450"))]},
    {"topic": "Knowledge distillation", "era": "2006 to 2015", "papers": [
        ("Bucilua, C., Caruana, R., & Niculescu-Mizil, A. (2006). Model compression. KDD 2006.", ""),
        ("Hinton, G., Vinyals, O., & Dean, J. (2015). Distilling the knowledge in a neural network. arXiv.", _ax("1503.02531"))]},
    {"topic": "Fully convolutional networks and U-Net", "era": "2015", "papers": [
        ("Long, J., Shelhamer, E., & Darrell, T. (2015). Fully convolutional networks for semantic segmentation. CVPR 2015.", _ax("1411.4038")),
        ("Ronneberger, O., Fischer, P., & Brox, T. (2015). U-Net: Convolutional networks for biomedical image segmentation. MICCAI 2015.", _ax("1505.04597"))]},
    {"topic": "Diffusion's first appearance and score matching", "era": "2015 to 2019", "papers": [
        ("Sohl-Dickstein, J., et al. (2015). Deep unsupervised learning using nonequilibrium thermodynamics. ICML 2015.", _ax("1503.03585")),
        ("Song, Y., & Ermon, S. (2019). Generative modeling by estimating gradients of the data distribution. NeurIPS 2019.", _ax("1907.05600"))]},
    {"topic": "Normalizing flows", "era": "2015 to 2016", "papers": [
        ("Rezende, D. J., & Mohamed, S. (2015). Variational inference with normalizing flows. ICML 2015.", _ax("1505.05770")),
        ("Dinh, L., Sohl-Dickstein, J., & Bengio, S. (2016). Density estimation using Real NVP. ICLR 2017.", _ax("1605.08803"))]},
    {"topic": "Deterministic policy gradients and DDPG", "era": "2014 to 2015", "papers": [
        ("Silver, D., et al. (2014). Deterministic policy gradient algorithms. ICML 2014.", ""),
        ("Lillicrap, T. P., et al. (2015). Continuous control with deep reinforcement learning. ICLR 2016.", _ax("1509.02971"))]},
    {"topic": "End-to-end visuomotor policies", "era": "2015", "papers": [
        ("Levine, S., Finn, C., Darrell, T., & Abbeel, P. (2015). End-to-end training of deep visuomotor policies. JMLR 2016.", _ax("1504.00702"))]},
    {"topic": "Trust regions, GAE, and PPO", "era": "2015 to 2017", "papers": [
        ("Schulman, J., et al. (2015). Trust region policy optimization. ICML 2015.", _ax("1502.05477")),
        ("Schulman, J., et al. (2015). High-dimensional continuous control using generalized advantage estimation. ICLR 2016.", _ax("1506.02438")),
        ("Schulman, J., et al. (2017). Proximal policy optimization algorithms. arXiv.", _ax("1707.06347"))]},
    {"topic": "Residual networks", "era": "2015 to 2016", "papers": [
        ("He, K., Zhang, X., Ren, S., & Sun, J. (2015). Deep residual learning for image recognition. CVPR 2016.", _ax("1512.03385")),
        ("He, K., Zhang, X., Ren, S., & Sun, J. (2016). Identity mappings in deep residual networks. ECCV 2016.", _ax("1603.05027"))],
     "notes": "ResNet won the ILSVRC 2015 classification task with an ensemble top-5 test error of 3.57%."},
    {"topic": "AlphaGo and AlphaGo Zero", "era": "2016 to 2017", "papers": [
        ("Silver, D., et al. (2016). Mastering the game of Go with deep neural networks and tree search. Nature.", ""),
        ("Silver, D., et al. (2017). Mastering the game of Go without human knowledge. Nature.", "")]},
    {"topic": "Graph neural networks and message passing", "era": "2016 to 2017", "papers": [
        ("Kipf, T. N., & Welling, M. (2016). Semi-supervised classification with graph convolutional networks. ICLR 2017.", _ax("1609.02907")),
        ("Gilmer, J., et al. (2017). Neural message passing for quantum chemistry. ICML 2017.", _ax("1704.01212"))]},
    {"topic": "Self-attention and cross-attention in the Transformer", "era": "2016 to 2017", "papers": [
        ("Cheng, J., Dong, L., & Lapata, M. (2016). Long short-term memory-networks for machine reading. EMNLP 2016.", _ax("1601.06733")),
        ("Lin, Z., et al. (2017). A structured self-attentive sentence embedding. ICLR 2017.", _ax("1703.03130")),
        ("Vaswani, A., et al. (2017). Attention is all you need. NeurIPS 2017.", _ax("1706.03762"))],
     "notes": "The base Transformer used d_model = 512, h = 8 heads, d_k = d_v = 64, and 6 encoder and 6 decoder layers. Each decoder layer has masked self-attention, then encoder-decoder (cross) attention, then a feed-forward network. Scaling by 1/sqrt(d_k) counters dot products whose variance grows with d_k. It used sinusoidal positional encodings."},
    {"topic": "Domain randomization and sim-to-real", "era": "2017", "papers": [
        ("Tobin, J., et al. (2017). Domain randomization for transferring deep neural networks from simulation to the real world. IROS 2017.", _ax("1703.06907")),
        ("Peng, X. B., Andrychowicz, M., Zaremba, W., & Abbeel, P. (2017). Sim-to-real transfer of robotic control with dynamics randomization. ICRA 2018.", _ax("1710.06537"))]},
    {"topic": "Pretraining arrives: ELMo, GPT, and BERT", "era": "2018", "papers": [
        ("Peters, M. E., et al. (2018). Deep contextualized word representations. NAACL 2018.", _ax("1802.05365")),
        ("Radford, A., Narasimhan, K., Salimans, T., & Sutskever, I. (2018). Improving language understanding by generative pre-training. OpenAI technical report.", ""),
        ("Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2018). BERT: Pre-training of deep bidirectional transformers for language understanding. NAACL 2019.", _ax("1810.04805"))]},
    {"topic": "Neural ordinary differential equations", "era": "2018", "papers": [
        ("Chen, R. T. Q., Rubanova, Y., Bettencourt, J., & Duvenaud, D. (2018). Neural ordinary differential equations. NeurIPS 2018.", _ax("1806.07366"))]},
    {"topic": "Protein folding: Anfinsen's hypothesis and the CASP challenge", "era": "1960s to 2020", "papers": [
        ("Anfinsen, C. B. (1973). Principles that govern the folding of protein chains. Science.", ""),
        ("Senior, A. W., et al. (2020). Improved protein structure prediction using potentials from deep learning. Nature.", "")],
     "notes": "Anfinsen's thermodynamic hypothesis holds that a protein's native structure is determined by its amino-acid sequence. Levinthal (1969) observed that a protein cannot find its fold by random search over conformations, which is known as Levinthal's paradox. CASP, the Critical Assessment of protein Structure Prediction, began in 1994 and is held every two years. The first AlphaFold (Senior et al.) placed first in CASP13 in 2018."},
    {"topic": "AlphaFold 2, RoseTTAFold, and AlphaFold 3", "era": "2020 to 2024", "papers": [
        ("Jumper, J., et al. (2021). Highly accurate protein structure prediction with AlphaFold. Nature.", ""),
        ("Baek, M., et al. (2021). Accurate prediction of protein structures and interactions using a three-track neural network. Science.", ""),
        ("Abramson, J., et al. (2024). Accurate structure prediction of biomolecular interactions with AlphaFold 3. Nature.", "")],
     "notes": "AlphaFold 2 was entered in CASP14 in 2020. Its architecture centers on the Evoformer, which jointly updates a multiple sequence alignment representation and a pair representation, followed by a structure module with invariant point attention. AlphaFold 3 replaced the structure module with a diffusion-based module. The 2024 Nobel Prize in Chemistry was awarded half to David Baker for computational protein design and half jointly to Demis Hassabis and John Jumper for protein structure prediction."},
    {"topic": "Computer-checked mathematics: from the four color theorem to Lean", "era": "1976 to 2021", "papers": [
        ("Appel, K., & Haken, W. (1977). Every planar map is four colorable. Illinois Journal of Mathematics.", ""),
        ("Gonthier, G. (2008). Formal proof: The four-color theorem. Notices of the AMS.", ""),
        ("Hales, T., et al. (2017). A formal proof of the Kepler conjecture. Forum of Mathematics, Pi.", ""),
        ("de Moura, L., & Ullrich, S. (2021). The Lean 4 theorem prover and programming language. CADE-28.", "")],
     "notes": "Appel and Haken announced their computer-assisted proof of the four color theorem in 1976. Gonthier's formal proof used the Coq proof assistant. The Flyspeck project behind the 2017 Kepler paper used HOL Light and Isabelle. Lean's community mathematics library is called Mathlib."},
    {"topic": "GPT-3 and in-context learning", "era": "2020", "papers": [
        ("Brown, T. B., et al. (2020). Language models are few-shot learners. NeurIPS 2020.", _ax("2005.14165"))]},
]

READER = ('You write for "The Model Desk", a daily brief for a reader with a computer science and robotics '
          'background who follows deep learning and wants to catch up to the current state of the art in '
          'technical depth: architectures, training paradigms, mathematics, and deployment.')
MATH_RULE = ('Where a formula genuinely clarifies the idea (an objective, an update rule, a complexity bound), '
             'include one in LaTeX, using \\( \\) inline or \\[ \\] for display. Escape every backslash for JSON.')
SHAPE = ('{"headline":"...","dek":"one-sentence summary","body":["paragraph","paragraph"],'
         '"why":"one sentence on why this matters for the field","terms":[{"term":"...","def":"under 15 words"}],'
         '"sources":[{"title":"...","url":"https://..."}]}')

client = anthropic.Anthropic()


def call(prompt: str, search: bool = False, max_tokens: int = 3000) -> str:
    kwargs = {"model": MODEL, "max_tokens": max_tokens}
    if search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]
    messages = [{"role": "user", "content": prompt}]
    texts = []
    for _ in range(6):
        resp = client.messages.create(messages=messages, **kwargs)
        texts += [b.text for b in resp.content if b.type == "text"]
        if resp.stop_reason != "pause_turn":
            break
        messages = [messages[0], {"role": "assistant", "content": resp.content}]
    return "".join(texts)


def fix_escapes(s: str) -> str:
    """Double the single backslashes LaTeX leaves in JSON (\\frac, \\theta, \\( ) so json.loads keeps them."""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c); i += 1; continue
        nx = s[i + 1] if i + 1 < n else ""
        if nx == "\\":
            out.append("\\\\"); i += 2; continue
        if nx in ('"', "/"):
            out.append(c + nx); i += 2; continue
        if nx == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6]):
            out.append(c); i += 1; continue
        if nx and nx in "bfnrt" and not s[i + 2:i + 3].isalpha():
            out.append(c); i += 1; continue
        out.append("\\\\"); i += 1
    return "".join(out)


def extract(text: str, open_c: str, close_c: str):
    start, end = text.find(open_c), text.rfind(close_c)
    if start < 0 or end <= start:
        raise ValueError("The reply had no readable JSON.")
    return json.loads(fix_escapes(text[start:end + 1]), strict=False)


def normalize(a: dict) -> dict:
    body = a.get("body") or []
    return {
        "headline": str(a.get("headline") or "Untitled"),
        "dek": str(a.get("dek") or ""),
        "body": [str(p) for p in body] if isinstance(body, list) else [str(body)],
        "why": str(a.get("why") or ""),
        "terms": [t for t in (a.get("terms") or []) if isinstance(t, dict) and t.get("term")],
        "sources": [s for s in (a.get("sources") or []) if isinstance(s, dict) and s.get("title")],
        "background": [str(p) for p in (a.get("background") or [])] if isinstance(a.get("background"), list) else ([str(a["background"])] if a.get("background") else []),
        "status": str(a.get("status") or ""),
        "deeper": [],
    }


SCI_SHAPE = ('{"headline":"...","dek":"one-sentence summary","background":["paragraph","paragraph"],'
             '"body":["paragraph","paragraph"],"status":"one sentence on verification status",'
             '"why":"one sentence on why this matters","terms":[{"term":"...","def":"under 15 words"}],'
             '"sources":[{"title":"...","url":"https://..."}]}')


def backstory_news(sec, n, avoid, date_long, focus):
    avoid_line = ("Do not repeat these recently covered stories: " + " | ".join(avoid)) if avoid else ""
    focus_line = f"Make the first article about {focus}. The others can be from any field." if focus else ""
    prompt = f"""{READER}
Today is {date_long}.
Section: {sec['name']}, covering {sec['brief']}.

Search the web for the most significant developments in this area from the past {sec.get('days', 7)} days, then
write {n} article(s) about different developments. {focus_line}
{avoid_line}

Each article has two parts, in this order:
1. "background": 2 paragraphs of history and context, written before any AI is mentioned. State the problem or
   theorem precisely (formally, with LaTeX where it helps), say who posed it and when, explain why it matters,
   and give the best earlier results with their authors and years.
2. "body": 2 paragraphs on what the AI system did and how, who reported it and when, and exactly what was shown.
"status": one sentence on verification. Say precisely whether the result is peer-reviewed, formally verified
(for example in Lean), reproduced independently, reviewed by named outside experts, or only claimed so far.

Accuracy rules. These matter more than anything else:
- Prefer primary sources: the paper, the lab's own post, the journal. Use press coverage only to confirm.
- Separate what was claimed from what has been verified. Never overstate a result.
- Never invent names, dates, or numbers. Leave out anything you can't confirm in search.
- {MATH_RULE}
- About 350 words per article. At most 2 terms and 3 sources per article. Sources must be URLs you found.
Respond with ONLY a JSON array of {n} object(s) shaped like {SCI_SHAPE}. No preamble, no commentary, no markdown fences."""
    arr = extract(call(prompt, search=True, max_tokens=6000), "[", "]")
    if not isinstance(arr, list) or not arr:
        raise ValueError("No stories were filed.")
    return [normalize(a) for a in arr[:n]]


def fact_check(a, sec, date_long):
    """Second pass with web search: verify each claim and correct or remove what doesn't hold up."""
    draft = {k: a[k] for k in ("headline", "dek", "background", "body", "status", "why", "terms", "sources")}
    prompt = f"""You are the fact-checking editor of a technical newsletter. Today is {date_long}.
Use web search to verify every specific claim in this draft from the {sec['name']} section: names, dates,
numbers, which organization and model did what, the history in the background, and the verification status.
Prefer primary sources.

Draft (JSON):
{json.dumps(draft, ensure_ascii=False)}

Correct anything wrong. Remove anything you cannot confirm. Make sure "status" does not overstate how well the
result has been verified. Keep only source URLs you confirmed. Keep the structure, length, and style.
Respond with ONLY the corrected JSON object shaped like {SCI_SHAPE}. No preamble, no markdown fences."""
    fixed = normalize(extract(call(prompt, search=True, max_tokens=5000), "{", "}"))
    fixed["checked"] = True
    return fixed


def news(sec, n, avoid, date_long):
    sid, name, brief = sec["id"], sec["name"], sec["brief"]
    avoid_line = ("Do not repeat these recently covered stories: " + " | ".join(avoid)) if avoid else ""
    prompt = f"""{READER}
Today is {date_long}.
Section: {name}, covering {brief}.

Search the web for the most significant developments in this area from roughly the past {sec.get('days', 7)} days, favoring the
most recent: papers, model releases, technical reports, and engineering write-ups. Then write {n} short news
article(s) about different developments.
{avoid_line}

Rules:
- Be concrete: name models, organizations, parameter counts, architectural choices, training objectives, benchmark results, and dates. Never invent numbers; leave out anything you can't confirm.
- {MATH_RULE}
- Body: 2 or 3 paragraphs, about 180 words in total, in your own words.
- At most 2 terms and 2 sources per article. Sources must be URLs you found in search.
- Respond with ONLY a JSON array of {n} object(s) shaped like {SHAPE}. No preamble, no commentary, no markdown fences."""
    arr = extract(call(prompt, search=True), "[", "]")
    if not isinstance(arr, list) or not arr:
        raise ValueError("No stories were filed.")
    return [normalize(a) for a in arr[:n]]


def section(sec, avoid, date_long, day_number):
    sid, last = sec["id"], None
    focus = sec["focus"][day_number % len(sec["focus"])] if sec.get("focus") else None
    for n in (2, 1):
        try:
            if sec.get("backstory"):
                articles = backstory_news(sec, n, avoid, date_long, focus)
            else:
                articles = news(sec, n, avoid, date_long)
            break
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"[{sid}] attempt with {n} stories failed: {e}")
    else:
        return {"status": "error", "error": f"This section wasn't filed today ({type(last).__name__})."}
    if sec.get("fact_check"):
        checked = []
        for a in articles:
            try:
                checked.append(fact_check(a, sec, date_long))
            except Exception as e:  # noqa: BLE001
                print(f"[{sid}] fact check failed for {a['headline']!r}: {e}")
                a["checked"] = False
                checked.append(a)
        articles = checked
    return {"status": "done", "articles": articles}


def primer(idx):
    topic = PRIMERS[idx]
    prompt = f"""{READER}
Write today's catch-up primer on: "{topic}".
Three paragraphs, about 280 words: the core idea and the problem it solves; the mechanism and key mathematics;
where it shows up in today's frontier and open-weight models.
- {MATH_RULE} Use at least one display equation.
- Terms: up to 3. Sources: up to 2 canonical papers. Only give a URL if it is an arXiv abstract page you are certain of; otherwise use an empty string for url.
- Respond with ONLY a JSON object shaped like {SHAPE}. No preamble, no markdown fences."""
    try:
        a = normalize(extract(call(prompt), "{", "}"))
        a = review(a, "No curated list for this topic. Keep paper titles and years only if they are certain.", SHAPE)
        return {"status": "done", "articles": [a]}
    except Exception as e:  # noqa: BLE001
        print(f"[primer] failed: {e}")
        return {"status": "error", "error": "Today's primer wasn't filed."}


def refs_text(tb):
    lines = "\n".join(f"- {cite}" for cite, _ in tb["papers"])
    if tb.get("notes"):
        lines += "\nVerified details you may use: " + tb["notes"]
    return lines


TB_SHAPE = ('{"headline":"...","dek":"one-sentence summary","body":["paragraph","paragraph","paragraph"],'
            '"why":"one sentence on why it still matters","terms":[{"term":"...","def":"under 15 words"}]}')
ACCURACY = """Accuracy rules. These matter more than anything else:
- Mention only papers from the reference list, with their authors and years exactly as listed. Do not add other papers, people, dates, venues, or benchmark numbers, except the verified details given.
- Every equation must be standard and correct, with each symbol defined.
- If you are not sure about a detail, leave it out."""


def review(article: dict, references: str, shape: str) -> dict:
    """A second, fact-checking pass over a draft. Returns the corrected article, or the draft if review fails."""
    prompt = f"""You are the fact-checking editor of a technical newsletter on machine learning.
Check the draft below against the references and standard textbook knowledge.

References:
{references}

Draft (JSON):
{json.dumps({k: article[k] for k in ("headline", "dek", "body", "why", "terms", "sources") if k in article}, ensure_ascii=False)}

Correct any equation errors and undefined symbols. Remove any name, date, venue, number, or attribution that
the references don't support and that isn't settled textbook knowledge. Remove any URL that isn't an arXiv
abstract page you are certain of. Keep the length, structure, and style otherwise.
Respond with ONLY the corrected JSON object shaped like {shape}. No preamble, no markdown fences."""
    try:
        fixed = normalize(extract(call(prompt, max_tokens=3000), "{", "}"))
        if "sources" not in shape:
            fixed["sources"] = article.get("sources", [])
        return fixed
    except Exception as e:  # noqa: BLE001
        print(f"[review] kept the unreviewed draft: {e}")
        return article


def throwback(idx):
    tb = THROWBACKS[idx]
    refs = refs_text(tb)
    prompt = f"""{READER}
Write today's Throwback, a look back at a landmark idea in machine learning: "{tb['topic']}" ({tb['era']}).

Reference list (curated and verified; your only source for names, titles, venues, and years):
{refs}

About 400 words in 3 or 4 paragraphs: the problem researchers faced at the time; the core mechanism, with its key
equations; and what changed afterward, including where the idea lives in today's models.
- {MATH_RULE} Use at least one display equation.
- Terms: up to 3.
{ACCURACY}
Respond with ONLY a JSON object shaped like {TB_SHAPE}. No preamble, no markdown fences."""
    try:
        a = normalize(extract(call(prompt), "{", "}"))
        a = review(a, refs, TB_SHAPE)
        a["sources"] = [{"title": cite, "url": url} for cite, url in tb["papers"]]
        a["era"] = tb["era"]
        return {"status": "done", "articles": [a]}
    except Exception as e:  # noqa: BLE001
        print(f"[throwback] failed: {e}")
        return {"status": "error", "error": "Today's throwback wasn't filed."}


def deeper(item):
    a, refs = item
    ref_block = f"\nReference list (your only source for names, titles, venues, and years):\n{refs}\n{ACCURACY}\n" if refs else ""
    prompt = f"""{READER}
Expand this brief into a deeper technical explainer of about 450 words.

Headline: {a['headline']}
Background: {' '.join(a.get('background') or [])}
Brief: {' '.join(a['body'])}
{ref_block}
Do not add names, dates, or numbers beyond those above unless they are settled textbook facts.
Cover the mechanism step by step, the key mathematics, how it compares with prior approaches, and open questions
or limitations. Use LaTeX with \\( \\) inline and \\[ \\] for display equations. Write plain paragraphs separated by
blank lines: no headings, no markdown, no preamble."""
    try:
        return [p.strip() for p in re.split(r"\n\s*\n", call(prompt, max_tokens=2000)) if p.strip()]
    except Exception as e:  # noqa: BLE001
        print(f"[deeper] failed for {a['headline']!r}: {e}")
        return []


def main():
    force = "--force" in sys.argv
    now = datetime.datetime.now(TZ)
    date = now.date().isoformat()
    path = EDITIONS / f"{date}.json"
    if not force and now.hour < BUILD_HOUR:
        print(f"It's {now:%H:%M} in {TZ.key}; editions print after {BUILD_HOUR}:00. Skipping.")
        return
    if not force and path.exists():
        print(f"Today's edition ({date}) is already printed. Skipping.")
        return

    index_path = EDITIONS / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"editions": [], "primerCursor": 0}
    rebuilding = path.exists()
    if rebuilding:
        old = json.loads(path.read_text())
        primer_idx = old.get("primerIndex", 0)
        tb_idx = old.get("throwbackIndex", index.get("throwbackCursor", 0) % len(THROWBACKS))
    else:
        primer_idx = index.get("primerCursor", 0) % len(PRIMERS)
        tb_idx = index.get("throwbackCursor", 0) % len(THROWBACKS)

    avoid = {}
    for d in [d for d in index["editions"] if d != date][:7]:
        p = EDITIONS / f"{d}.json"
        if p.exists():
            for sid, sec in json.loads(p.read_text()).get("sections", {}).items():
                avoid.setdefault(sid, []).extend(a["headline"] for a in sec.get("articles", []))

    date_long = now.strftime("%A, %B %-d, %Y")
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        day_number = now.date().toordinal()
        futures = {sec["id"]: ex.submit(section, sec, avoid.get(sec["id"], [])[:12], date_long, day_number) for sec in SECTIONS}
        futures["primer"] = ex.submit(primer, primer_idx)
        futures["throwback"] = ex.submit(throwback, tb_idx)
        sections = {sid: f.result() for sid, f in futures.items()}

    if not any(sections[sec["id"]]["status"] == "done" for sec in SECTIONS):
        sys.exit("Every news section failed; not publishing. Check the API key and the logs above.")

    if DEEPER:
        items = [(a, refs_text(THROWBACKS[tb_idx]) if sid == "throwback" else None)
                 for sid, sec in sections.items() for a in sec.get("articles", [])]
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            for (a, _), paras in zip(items, ex.map(deeper, items)):
                a["deeper"] = paras

    edition = {"date": date, "created": now.isoformat(), "primerIndex": primer_idx, "throwbackIndex": tb_idx, "sections": sections}
    EDITIONS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(edition, ensure_ascii=False, indent=1))

    index["editions"] = [date] + [d for d in index["editions"] if d != date]
    if not rebuilding:
        index["primerCursor"] = primer_idx + 1
        index["throwbackCursor"] = tb_idx + 1
    index["curriculum"] = PRIMERS
    index["throwbacks"] = [{"topic": t["topic"], "era": t["era"]} for t in THROWBACKS]
    index["sections"] = [{"id": sec["id"], "name": sec["name"]} for sec in SECTIONS]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"Printed the edition for {date}.")


if __name__ == "__main__":
    main()
