# Crawler user-agent roles

Used to interpret robots.txt policy. **Role, not vendor, decides whether a block is a
defect.** This table ages: new agents appear a few times a year. An agent token that is
not listed here has role `unknown` and must never be the sole basis for a finding.

| Token | Operator | Role | Blocking it costs |
| --- | --- | --- | --- |
| `GPTBot` | OpenAI | training | nothing in citations |
| `OAI-SearchBot` | OpenAI | retrieval | eligibility for ChatGPT search answers |
| `ChatGPT-User` | OpenAI | user-triggered | answers about a page a user asked about |
| `ClaudeBot` | Anthropic | training | nothing in citations |
| `Claude-SearchBot` | Anthropic | retrieval | eligibility for Claude web answers |
| `Claude-User` | Anthropic | user-triggered | answers about a page a user asked about |
| `anthropic-ai`, `Claude-Web` | Anthropic | legacy or training | nothing in citations |
| `PerplexityBot` | Perplexity | retrieval | eligibility for Perplexity answers |
| `Perplexity-User` | Perplexity | user-triggered | live fetches |
| `Googlebot` | Google | retrieval | Google Search **and** Google's AI surfaces |
| `Google-Extended` | Google | training | Gemini and Vertex training only |
| `Bingbot` | Microsoft | retrieval | Bing index and the assistants that read it |
| `Applebot` | Apple | retrieval | Apple surfaces |
| `Applebot-Extended` | Apple | training | nothing in citations |
| `CCBot` | Common Crawl | training | nothing directly |
| `Meta-ExternalAgent` | Meta | training | nothing in citations |
| `Bytespider` | ByteDance | training | nothing in citations |

## Interpretation rules

1. **Training blocked, retrieval allowed** — `ACC.TRAINING_ONLY_BLOCK`, severity `info`.
   Frame it as a deliberate trade-off and state both sides. Do not recommend reversing it;
   recommend making the intent explicit and reviewing it deliberately.
2. **Any retrieval or user-triggered agent disallowed from content** —
   `ACC.ROBOTS_BLOCKS_RETRIEVAL`. This is the defect.
3. **`Googlebot` disallowed** — treat as retrieval. Note that Google's AI surfaces cannot
   be opted out of separately from Google Search; `Google-Extended` only affects training.
4. **Unknown token disallowed** — no finding. Record it in the evidence of a related
   finding at most.
5. **Verification caveat for the report.** A user-agent string is trivially spoofed. When
   recommending server-log monitoring, recommend verifying crawlers by their operators'
   published IP ranges rather than by the header.
6. **robots.txt is a norm, not an enforcement mechanism.** Some crawlers ignore it. Never
   tell a site owner that a robots directive guarantees either exclusion or inclusion.
