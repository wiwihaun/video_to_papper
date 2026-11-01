# Method provenance — what is verified, and what is not

This file exists so that nobody — the user, a colleague, or a future session — mistakes
inference for sourcing. If the user asks "where did this method come from?", answer from
this file and not from the rest of the skill.

## The source video

| Field | Value | Status |
|---|---|---|
| URL | `https://www.youtube.com/watch?v=F7WEN5wOGZs` | given by the user |
| Title | 投資特斯拉看這兩個數字，其他都是噪音 | **verified** via YouTube oEmbed API |
| Channel | Terry Chen 泰瑞 | **verified** via YouTube oEmbed API |
| Published | ~early October 2026 ("28 days ago" as of 2026-11-01) | approximate, from search metadata |
| Subject | Tesla ahead of Q3 earnings: Robotaxi and Waymo fleet progress, extension into Semi and Optimus, and which FSD metrics to watch | **described in search metadata**, not read from the video |

## What could not be obtained

**The transcript was not retrieved. No part of this skill is derived from the video's
actual spoken content.**

Three routes were attempted on 2026-11-01 from the cloud container:

1. **`yt-dlp` subtitle download** — failed. YouTube returned `HTTP 429 Too Many
   Requests`, then `Sign in to confirm you're not a bot`. The container's IP is
   rate-limited, and no JavaScript runtime is available for the current extractor.
2. **Installing a JS runtime (deno)** to satisfy the extractor — blocked by the
   session's permission policy (external code download).
3. **WhisperAI transcription service** — the MCP connector was disconnected and needs
   re-authentication. It also takes a direct media file URL, not a YouTube page URL,
   so it would not have resolved this on its own.

Retrying with different YouTube player clients was **not** attempted: that is
bot-check circumvention, and the session's policy correctly refuses it.

## What this skill is actually built on

The workflow has two distinguishable layers. Keep them distinguishable.

**Layer 1 — the organising thesis, taken from the video's title.**
The title asserts a specific and non-obvious claim: that for this company *two numbers
determine the answer and everything else is noise*. That claim is verified — it is the
video's own title. It is the spine of this skill: Phase 2 (driver isolation), the
mandatory noise list, and the rule that scenarios may differ only in the isolated
drivers all follow from it. The subject matter also tells us the author's two numbers
for Tesla were operating KPIs (FSD/Robotaxi fleet metrics), not accounting ratios —
which is why Phase 2 requires drivers to be *observable in a data release*.

**Layer 2 — the valuation machinery, which is standard institutional practice and not
from the video.** FCFF construction, WACC, Gordon versus exit-multiple terminal value,
sum-of-the-parts with probability-weighted option pools, reverse-DCF of market-implied
expectations, scenario probability weighting, and the sell-side report format are all
conventional professional method. They are included because the Layer 1 thesis needs a
rigorous engine to be more than a slogan, not because the video specified them.

**What is therefore unknown:** the author's two specific numbers for Tesla, his
quantitative method for converting them into a value, any price target he gave, and his
reasoning. Those are in the audio, and the audio was not read. Do not attribute any
specific technique in this skill to Terry Chen.

## How to upgrade this from inference to sourcing

If the user supplies the transcript — see `docs/transcript/README.md` for the four ways
to get it in — then:

1. Save it verbatim to `docs/transcript/F7WEN5wOGZs.md` with its retrieval date.
2. Extract the author's actual method: his two numbers, his valuation arithmetic, his
   scenario structure, and the specific items he dismissed as noise.
3. Revise Phases 1–7 where the real method differs from the standard practice used as a
   placeholder, and record the diff in this file.
4. Rewrite this section to state what is now sourced from the transcript, keeping the
   Layer 1 / Layer 2 distinction accurate.

Until that happens, this skill is a sound institutional valuation workflow organised
around a thesis the video's title states. That is a fair description of it. Any stronger
claim is not.
