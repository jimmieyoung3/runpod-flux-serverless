#!/usr/bin/env python3
"""Render the case-study submission PDF from the measured results.

FROZEN. This script reproduces the PDF exactly as it was submitted, including
the billing error described in docs/CORRECTIONS.md. It is deliberately not
updated, so that the submitted artifact stays reproducible from source. The
corrected analysis lives in docs/RESULTS.md and docs/CORRECTIONS.md.

    .venv/bin/python scripts/build_submission_pdf.py

Everything here is content; the numbers come from docs/RESULTS.md and the
benchmark JSON, so regenerating after a new benchmark run keeps them in sync.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"
OUT = ROOT / "docs" / "Jimmie-Young-RunPod-Serverless-Case-Study.pdf"

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5b6472")
ACCENT = colors.HexColor("#3f6cd4")
RULE = colors.HexColor("#d8dce3")
BAND = colors.HexColor("#f2f4f8")

REPO = "https://github.com/jimmieyoung3/runpod-flux-serverless"

ss = getSampleStyleSheet()
S = {
    "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                         fontSize=17, leading=21, spaceBefore=16, spaceAfter=7, textColor=INK),
    "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                         fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=4, textColor=INK),
    "body": ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica",
                           fontSize=9.6, leading=14.2, spaceAfter=7, textColor=INK, alignment=TA_LEFT),
    "small": ParagraphStyle("small", parent=ss["BodyText"], fontName="Helvetica",
                            fontSize=8.3, leading=11.6, textColor=MUTED, spaceAfter=5),
    "code": ParagraphStyle("code", parent=ss["BodyText"], fontName="Courier",
                           fontSize=8.1, leading=11.4, textColor=INK,
                           backColor=BAND, borderPadding=6, spaceAfter=8),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11.6, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11.6, textColor=INK),
    "caption": ParagraphStyle("caption", fontName="Helvetica", fontSize=7.8, leading=10.5,
                              textColor=MUTED, spaceBefore=3),
}


def P(t, s="body"):
    return Paragraph(t, S[s])


def table(rows, widths, header=True):
    data = [[Paragraph(str(c), S["cellb"] if (header and r == 0) else S["cell"])
             for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
        ("BOX", (0, 0), (-1, -1), 0.6, RULE),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), BAND),
                  ("LINEBELOW", (0, 0), (-1, 0), 0.8, MUTED)]
    t.setStyle(TableStyle(style))
    return t


def figure(filename, caption, width=82 * mm):
    path = ASSETS / filename
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(str(path)).getSize()
    img = Image(str(path), width=width, height=width * ih / iw)
    return KeepTogether([img, Paragraph(caption, S["caption"]), Spacer(1, 7)])


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 12 * mm, "Jimmie Young  ·  RunPod Serverless Endpoint Case Study")
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"{doc.page}")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
    canvas.restoreState()


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4,
                          leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=17 * mm, bottomMargin=20 * mm,
                          title="RunPod Serverless Endpoint Case Study",
                          author="Jimmie Young")
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=header_footer)])

    F = []  # flowables
    W = doc.width

    # ---------------------------------------------------------------- title
    F += [Spacer(1, 28),
          Paragraph("RunPod Serverless Endpoint", ParagraphStyle(
              "t", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=INK)),
          Paragraph("FLUX.1-dev text-to-image, deployed and measured", ParagraphStyle(
              "st", fontName="Helvetica", fontSize=13, leading=18, textColor=ACCENT, spaceBefore=4)),
          Spacer(1, 16),
          table([
              ["Submitted by", "Jimmie Young"],
              ["Date", "22 September 2026"],
              ["Repository", f'<link href="{REPO}"><font color="#3f6cd4">{REPO}</font></link>'],
              ["Endpoint ID", "<font face='Courier'>ux61jghq0twkgq</font>"],
              ["Image", "<font face='Courier'>docker.io/jimmieyoung3/flux-runpod:v1</font> (private, 29.87 GB)"],
              ["Model", "black-forest-labs/FLUX.1-dev, bfloat16"],
          ], [34 * mm, W - 34 * mm], header=False),
          Spacer(1, 16)]

    F += [P("Summary", "h2"),
          P("A RunPod serverless endpoint that accepts a text prompt over HTTP and returns a "
            "generated image. The FLUX.1-dev weights are baked into the Docker image, so a worker "
            "loads the model from local disk in <b>7.2 seconds</b> rather than pulling 33.7 GB from "
            "the Hugging Face Hub. Warm generation of a 1024&#215;1024 image at 28 steps takes "
            "<b>14.1 s on an A100</b> or <b>30.3 s on an A40</b>, at a cost of about "
            "<b>one cent per image</b> on either. Total cost of building, deploying and benchmarking "
            "the whole exercise was <b>$0.85</b>."),
          P("The sections below cover the architecture, the handler and image design, two platform "
            "constraints that materially shaped the build, the measured results, and what I would "
            "change for production.")]

    F += [figure("flux-20260922-122015-42-0.png",
                 "Endpoint output. Prompt: “a cinematic photograph of a glass terrarium on a windowsill "
                 "at golden hour, shallow depth of field, 85mm”. Seed 42, 1024&#215;1024, 28 steps.",
                 width=W * 0.52)]

    F += [PageBreak()]

    # ------------------------------------------------------------ architecture
    F += [P("1. Architecture", "h1"),
          P("The endpoint is a single-purpose GPU worker. RunPod owns the queue, autoscaling and "
            "HTTP surface; the worker owns model loading and inference."),
          Paragraph(
              "client&nbsp;&nbsp;--&nbsp;&nbsp;POST /runsync {\"input\":{\"prompt\": ...}}&nbsp;&nbsp;--&gt;&nbsp;&nbsp;RunPod queue<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;|<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;v<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;GPU worker (0 to 2, scale to zero)<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;|- import: FluxPipeline.from_pretrained(/models/flux)<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;|- warmup: one 512px / 1-step pass<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;\\- per request: validate &gt; generate &gt; encode base64",
              S["code"]),
          P("Three decisions define the design.", "h2"),
          table([
              ["Decision", "Rationale", "Measured effect"],
              ["Weights baked into the image",
               "Removes the Hub from the critical path; a cold worker reads from local disk.",
               "Model ready in <b>7.2 s</b> vs ~10 min from the Hub"],
              ["Pipeline loaded at module import",
               "RunPod attributes import time to worker start-up, not to billed request time.",
               "Warm requests bill only inference"],
              ["One job per worker (<font face='Courier'>concurrency_modifier</font> = 1)",
               "Generation saturates the GPU; two concurrent 1024px jobs slow each other.",
               "Execution stayed flat at 30.4 s under 2&#215; load"],
          ], [44 * mm, W - 44 * mm - 38 * mm, 38 * mm]),
          P("A one-step warm-up pass runs at start-up so the first paying request does not absorb "
            "CUDA kernel autotuning and lazy initialisation.")]

    # ------------------------------------------------------------ the handler
    F += [P("2. The handler", "h1"),
          P("<font face='Courier'>src/handler.py</font> is the RunPod entry point; "
            "<font face='Courier'>src/predict.py</font> owns the pipeline and "
            "<font face='Courier'>src/schema.py</font> validates input. Validation is deliberately "
            "free of torch and diffusers so it unit-tests on any machine. 25 tests run without a GPU."),
          Paragraph(
              "def handler(job):<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;params = validate(job.get(\"input\"), DEFAULTS)<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;result = predictor.generate(params)<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;return {\"images\": [...], \"seed\": result.seed, \"metrics\": {...}}<br/><br/>"
              "runpod.serverless.start({\"handler\": handler,<br/>"
              "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;\"concurrency_modifier\": adjust_concurrency})",
              S["code"]),
          P("Notable details", "h2"),
          table([
              ["Behaviour", "Why"],
              ["Dimensions snap to a multiple of 16",
               "FLUX packs latents 2&#215;2 on top of the VAE's 8&#215; downscale. Other values silently "
               "produce a differently sized image, so the handler rounds and reports rather than failing."],
              ["No <font face='Courier'>negative_prompt</font>",
               "FLUX.1 is guidance-distilled and <font face='Courier'>FluxPipeline</font> has no negative "
               "conditioning. Silently accepting the field would be worse than rejecting it."],
              ["Errors return HTTP 200 with an <font face='Courier'>error</font> field",
               "RunPod reserves non-2xx for platform failures; application errors belong in the body. "
               "Validation errors are separated from inference errors so a client mistake does not burn a retry."],
              ["Booleans rejected where numbers are expected",
               "<font face='Courier'>bool</font> subclasses <font face='Courier'>int</font> in Python, so "
               "<font face='Courier'>steps=True</font> would otherwise silently mean 1 step."],
              ["Optional S3 delivery",
               "Base64 keeps the endpoint dependency-free, but exceeds RunPod's ~20 MB response ceiling at "
               "about four 1024px PNGs. Setting <font face='Courier'>BUCKET_ENDPOINT_URL</font> switches to presigned URLs."],
          ], [46 * mm, W - 46 * mm])]

    # No page break here: the handler table used to orphan a single row onto an
    # otherwise empty page. Letting section 3 flow straight on fills it.

    # ------------------------------------------------------- build constraints
    F += [P("3. Two platform constraints", "h1"),
          P("The image is 29.87 GB, which makes <i>where you build it</i> an engineering problem. "
            "Both constraints below were discovered during the build and are documented in the repository."),
          P("Buildah and Podman cannot run inside a RunPod pod", "h2"),
          P("RunPod pods have no <font face='Courier'>CAP_SYS_ADMIN</font>, and the hosts set "
            "<font face='Courier'>apparmor_restrict_unprivileged_userns=1</font>, so "
            "<font face='Courier'>unshare(CLONE_NEWUSER)</font> is denied. Both tools re-exec into a user "
            "namespace at start-up, before they honour <font face='Courier'>--isolation chroot</font>, so "
            "even <font face='Courier'>buildah containers</font> fails. Kaniko uses no namespaces and is the "
            "workable builder. RunPod's own in-pod build tutorial reaches for Bazel and crane for the same reason."),
          P("Kaniko destroys the pod it runs in", "h2"),
          P("Kaniko extracts the base image over <font face='Courier'>/</font>, deleting the userland that "
            "<font face='Courier'>sshd</font> depends on. SSH dies mid-build and does not recover; preserving "
            "the sshd binary via <font face='Courier'>--ignore-path</font> is not enough, because its PAM and "
            "libc dependencies go too. The consequence is architectural: Kaniko must <b>push the image itself</b>, "
            "because building to a local tarball strands the result on a pod you can no longer reach. The build "
            "runs detached under <font face='Courier'>setsid</font> and is monitored from outside against the registry."),
          P("Keeping the token out of the image", "h2"),
          P("Kaniko does not implement <font face='Courier'>RUN --mount=type=secret</font>. Passing the Hugging "
            "Face token as a build argument would persist it in the image history, so instead the weights are "
            "downloaded into the build context beforehand and simply copied in. The token never enters the image, "
            "its history or its layers. That was verified by auditing the published image config, which contains zero "
            "token-shaped strings. The cost is peak build disk, since the weights exist twice during the build."),
          P("RunPod's GitHub integration would otherwise be the natural choice. It is ruled out on two counts: "
            "it caps <font face='Courier'>docker build</font> at 30 minutes, and it exposes no build-time secret, "
            "which a gated repository such as FLUX.1-dev requires."),
          P("Build pipeline as deployed", "h2"),
          table([
              ["Stage", "Where", "Time"],
              ["Fetch 33.7 GB of weights (79 files)", "RunPod CPU pod, 32 vCPU", "~3 min"],
              ["Kaniko build + push of 29.87 GB", "same pod, detached", "~26 min"],
              ["Total build cost", "two pods, incl. one failed attempt", "<b>$0.66</b>"],
          ], [62 * mm, W - 62 * mm - 26 * mm, 26 * mm]),
          P("Root-level single-file checkpoints in the FLUX.1-dev repository duplicate the sharded diffusers "
            "folders that <font face='Courier'>FluxPipeline</font> actually loads. Excluding them cut the "
            "download from 57.8 GB to 33.7 GB.", "small")]

    F += [PageBreak()]

    # ------------------------------------------------------------- results
    F += [P("4. Results", "h1"),
          P("Measured against the live endpoint on 22 September 2026. "
            "<font face='Courier'>executionTime</font> is what RunPod bills; "
            "<font face='Courier'>delayTime</font> is queue plus worker start-up."),
          P("Latency at 1024&#215;1024, 28 steps, guidance 3.5", "h2"),
          table([
              ["Scenario", "delayTime", "executionTime", "Wall"],
              ["First-ever cold start, health call only", "<b>609 s</b>", "0.04 s", "650 s"],
              ["Cold start, image cached on host (A100)", "<b>15.5 s</b>", "16.0 s", "35.2 s"],
              ["Warm, A40 (mean of 5)", "0.69 s", "<b>30.32 s</b> (σ 0.06)", "33.1 s"],
              ["Warm, A100 (mean of 4)", "0.80 s", "<b>14.07 s</b> (σ 0.04)", "16.0 s"],
              ["2 concurrent, A40", "16.42 s", "30.40 s", "49.9 s"],
          ], [64 * mm, 25 * mm, 40 * mm, W - 129 * mm]),
          P("The first row is a health call, which reports model and GPU information without generating, so its "
            "executionTime covers only the round trip. It is listed because its delayTime captures the one-time "
            "cost of scheduling a worker and pulling a 30 GB image onto a host that had never seen it."),
          P("A standard deviation of 0.06 s across warm runs confirms the pipeline stays resident and nothing "
            "is re-loaded per request. Model load from the baked weights is 7.2 to 8.0 s."),
          P("Cost", "h2"),
          table([
              ["GPU", "$/hr", "s/image", "$/image", "Images per $1"],
              ["A40 48 GB", "$1.22", "30.32", "<b>$0.0103</b>", "97"],
              ["A100-SXM4 80 GB", "$2.72", "14.07", "<b>$0.0106</b>", "93"],
          ], [44 * mm, 22 * mm, 24 * mm, 26 * mm, W - 116 * mm]),
          P("The most useful finding: <b>cost per image is nearly GPU-independent</b>. A 2.2&#215; faster card "
            "costs 2.2&#215; more per second, so the two differ by 3%. Choose the GPU tier for the latency you "
            "need, not to save money. What actually moves cost is step count, resolution, and idle workers."),
          P("What a 30 GB image costs you", "h2"),
          P("The first request sat in <font face='Courier'>throttled</font> for roughly 10 minutes before a worker "
            "was placed, and widening from 7 to 11 GPU tiers did not help, which points at the image rather than "
            "GPU scarcity. A host must cache ~30 GB before it can start a worker, a smaller pool than “any host "
            "with a free GPU”. So the baked-weights decision has a measurable cost as well as a measurable benefit:"),
          table([
              ["", "Baked weights (deployed)", "Network volume (fallback)"],
              ["Model available in", "<b>7.2 s</b>", "~10 min first boot, then volume read"],
              ["First scheduling", "~10 min throttle", "fast, ~9 GB image"],
              ["Runtime Hub dependency", "none", "first boot only"],
          ], [38 * mm, 44 * mm, W - 82 * mm]),
          P("For a steady endpoint the baked image is the better trade. For one that scales from zero often, or "
            "across many regions, the volume variant schedules faster. It is implemented in the repository as "
            "<font face='Courier'>Dockerfile.volume</font>.")]

    F += [PageBreak()]

    # ------------------------------------------------------------- samples
    F += [P("5. Sample generations", "h1"),
          P("Unmodified endpoint output. All 28 steps, guidance 3.5.")]

    pairs = [
        ("flux-20260922-122546-7-0.png",
         "Seed 7. “a hand-lettered enamel shop sign reading FLUX ON RUNPOD…”. Text renders correctly."),
        ("flux-20260922-122620-1234-0.png",
         "Seed 1234. “an isometric cutaway of a tiny mechanical workshop… tilt-shift”."),
        ("flux-20260922-122955-2026-0.png",
         "Seed 2026. “a lone lighthouse on a basalt cliff during a winter storm”. Generated on the image-cached cold start, 15.5 s delay."),
        ("flux-20260922-122650-99-0.png",
         "Seed 99, 832&#215;1216, non-square output exercising the dimension snapping in schema.py."),
    ]
    # A KeepTogether inside a table cell makes reportlab compute an unbounded
    # row height, so images and captions go in as plain flowables, two per row.
    col = (W - 10 * mm) / 2

    def cell_image(name, width, max_h=70 * mm):
        """Fit inside the column, but cap height so a portrait sitting beside a
        square image does not push its neighbour's caption down the page."""
        from reportlab.lib.utils import ImageReader
        iw, ih = ImageReader(str(ASSETS / name)).getSize()
        w = min(width, max_h * iw / ih)
        return Image(str(ASSETS / name), width=w, height=w * ih / iw)

    grid = [
        [cell_image(pairs[0][0], col), cell_image(pairs[1][0], col)],
        [Paragraph(pairs[0][1], S["caption"]), Paragraph(pairs[1][1], S["caption"])],
        [cell_image(pairs[2][0], col), cell_image(pairs[3][0], col)],
        [Paragraph(pairs[2][1], S["caption"]), Paragraph(pairs[3][1], S["caption"])],
    ]
    g = Table(grid, colWidths=[col + 5 * mm, col + 5 * mm], hAlign="LEFT")
    g.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
                           ("BOTTOMPADDING", (0, 0), (-1, 0), 3),
                           ("BOTTOMPADDING", (0, 2), (-1, 2), 3)]))
    F += [g]

    F += [PageBreak()]

    # ------------------------------------------------------------- using it
    F += [P("6. Using the endpoint", "h1"),
          Paragraph(
              "curl -s -X POST https://api.runpod.ai/v2/ux61jghq0twkgq/runsync \\<br/>"
              "&nbsp;&nbsp;-H \"Authorization: Bearer $RUNPOD_API_KEY\" \\<br/>"
              "&nbsp;&nbsp;-H \"Content-Type: application/json\" \\<br/>"
              "&nbsp;&nbsp;-d '{\"input\": {\"prompt\": \"a red fox in a snowy forest\", \"seed\": 7}}' &gt; resp.json<br/><br/>"
              "python -c \"import json, base64; d = json.load(open('resp.json'))['output']; open('out.png', 'wb').write(base64.b64decode(d['images'][0]))\"",
              S["code"]),
          P("Or with the repository's client, which saves the decoded image and prints the metrics:"),
          Paragraph(
              "python client/call_endpoint.py \"a red fox in a snowy forest\" --seed 7<br/>"
              "python client/call_endpoint.py --health&nbsp;&nbsp;&nbsp;&nbsp;# model + GPU report<br/>"
              "python client/benchmark.py --runs 5 --gpu-rate 0.000339",
              S["code"]),
          P("Request fields", "h2"),
          table([
              ["Field", "Default", "Notes"],
              ["<font face='Courier'>prompt</font>", "required", "≤ 2000 characters"],
              ["<font face='Courier'>width</font>, <font face='Courier'>height</font>", "1024", "snapped to a multiple of 16, clamped 256-1536"],
              ["<font face='Courier'>num_inference_steps</font>", "28", "1-50"],
              ["<font face='Courier'>guidance_scale</font>", "3.5", "0-20"],
              ["<font face='Courier'>seed</font>", "random", "the seed used is always returned"],
              ["<font face='Courier'>num_images</font>", "1", "1-4"],
              ["<font face='Courier'>output_format</font>", "PNG", "PNG, JPEG or WEBP"],
              ["<font face='Courier'>action</font>", "(none)", "<font face='Courier'>\"health\"</font> returns model/GPU info without generating"],
          ], [44 * mm, 22 * mm, W - 66 * mm]),
          P("7. What I would change for production", "h1"),
          table([
              ["Change", "Why"],
              ["Ship the network-volume variant across regions",
               "The 30 GB image limits which hosts can place a worker. A ~9 GB image plus a pre-populated "
               "volume schedules faster and still avoids a per-boot download."],
              ["Return presigned S3 URLs, not base64",
               "Base64 is convenient for review but inflates payloads by a third and hits RunPod's ~20 MB "
               "response ceiling at about four 1024px PNGs. The code path already exists."],
              ["Pin the GPU tier once traffic is known",
               "Latency varied from 14 to 30 s purely on which card was scheduled. Latency-sensitive traffic should "
               "pin the faster tier; batch traffic should not pay for it."],
              ["Add request-level observability",
               "The handler returns per-request metrics, but nothing aggregates them. Prometheus or a log sink "
               "would make regressions visible."],
              ["Quantised variants for throughput",
               "fp8 or NF4 transformer weights roughly halve both load time and VRAM, at some quality cost, "
               "worth measuring against the bf16 baseline recorded here."],
          ], [46 * mm, W - 46 * mm]),
          KeepTogether([
            P("8. Knowledge base articles", "h1"),
            P("Each problem hit during this build was written up as a customer-facing article in "
              "<font face='Courier'>docs/kb/</font>, in the shape a support article needs: what you see, "
              "what causes it, the commands that confirm it, and what to do about it. Where a cause is "
              "inferred rather than proven, the article says so."),
            table([
                ["Article", "Issue it resolves"],
                ["KB-001", "Container build on a Pod fails with <font face='Courier'>unshare(CLONE_NEWUSER): Operation not permitted</font>. "
                           "Includes the four commands that confirm it and the Kaniko workaround, with its side effects."],
                ["KB-002", "Serverless workers stay <font face='Courier'>throttled</font> and jobs sit in the queue. "
                           "How to tell GPU capacity apart from an image too large for hosts to cache."],
                ["KB-003", "The first request to a new endpoint times out while later ones succeed. "
                           "Why <font face='Courier'>/run</font> and polling beats <font face='Courier'>/runsync</font> when cold, and how to shorten cold starts."],
                ["KB-004", "Keeping Hugging Face and registry credentials out of an image, including the case where "
                           "BuildKit secrets are unavailable, and how to verify the published image rather than assume."],
            ], [20 * mm, W - 20 * mm])
          ]),
          Spacer(1, 10),
          P(f'Full source, tests and deployment runbook: <link href="{REPO}">'
            f'<font color="#3f6cd4">{REPO}</font></link>', "small"),
          P("FLUX.1-dev weights are covered by the FLUX.1-dev Non-Commercial Licence, which is why the built "
            "image is held in a private registry and not redistributed.", "small")]

    doc.build(F)
    print(f"wrote {OUT}  ({OUT.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    build()
