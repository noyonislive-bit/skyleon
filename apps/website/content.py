"""
Shared marketing content for the public website.

Everything that appears on more than one page (services, industries, solutions,
FAQs, workflow steps …) lives here so templates stay DRY and copy is edited in
one place.

Copy rules (keep them when editing):
  * No invented clients, logos, testimonials, certifications, awards or fixed
    headcount / volume numbers — use qualitative proof points instead.
  * We do not develop AI models. We provide annotated datasets that support the
    training, evaluation and improvement of computer vision and AI models.
  * Tools: we work with the client's preferred platform or adapt to their
    workflow — never imply every project uses every platform.
  * Output formats always depend on project requirements.

Tailwind scans this file, so the literal class strings in TONES are compiled.
Never hard-code the company name here — use BRAND_NAME (from core.site_settings.BRAND).
"""

from apps.core.site_settings import BRAND

BRAND_NAME = BRAND["name"]

DATASET_STATEMENT = (
    "We provide high-quality annotated datasets to support the training, evaluation and improvement "
    "of computer vision and AI models."
)
SCALE_STATEMENT = (
    "We can scale dedicated annotation teams based on project volume, timeline and quality requirements."
)
TOOLS_STATEMENT = "We can work with your preferred annotation platform or adapt to your existing workflow."
FORMATS_NOTE = "Final delivery formats depend on your project requirements."

# Colour tones for annotation-style accents (label palette).
TONES = {
    "lime": {
        "text": "text-label-lime", "bg": "bg-label-lime", "soft": "bg-label-lime/10",
        "ring": "ring-label-lime/30", "chip": "bg-label-lime/10 text-lime-700 ring-label-lime/40",
        "dark_chip": "bg-label-lime/10 text-label-lime ring-label-lime/25", "hex": "#a3e635",
    },
    "cyan": {
        "text": "text-label-cyan", "bg": "bg-label-cyan", "soft": "bg-label-cyan/10",
        "ring": "ring-label-cyan/30", "chip": "bg-cyan-50 text-cyan-700 ring-cyan-500/30",
        "dark_chip": "bg-label-cyan/10 text-label-cyan ring-label-cyan/25", "hex": "#22d3ee",
    },
    "amber": {
        "text": "text-label-amber", "bg": "bg-label-amber", "soft": "bg-label-amber/10",
        "ring": "ring-label-amber/30", "chip": "bg-amber-50 text-amber-700 ring-amber-500/30",
        "dark_chip": "bg-label-amber/10 text-label-amber ring-label-amber/25", "hex": "#fbbf24",
    },
    "pink": {
        "text": "text-label-pink", "bg": "bg-label-pink", "soft": "bg-label-pink/10",
        "ring": "ring-label-pink/30", "chip": "bg-pink-50 text-pink-700 ring-pink-500/30",
        "dark_chip": "bg-label-pink/10 text-label-pink ring-label-pink/25", "hex": "#f472b6",
    },
    "violet": {
        "text": "text-label-violet", "bg": "bg-label-violet", "soft": "bg-label-violet/10",
        "ring": "ring-label-violet/30", "chip": "bg-violet-50 text-violet-700 ring-violet-500/30",
        "dark_chip": "bg-label-violet/10 text-label-violet ring-label-violet/25", "hex": "#a78bfa",
    },
    "brand": {
        "text": "text-brand-400", "bg": "bg-brand-500", "soft": "bg-brand-500/10",
        "ring": "ring-brand-400/30", "chip": "bg-brand-50 text-brand-700 ring-brand-500/30",
        "dark_chip": "bg-brand-400/10 text-brand-300 ring-brand-400/25", "hex": "#8183fa",
    },
}


def _tone(name):
    return TONES[name]


# ─── Services ───────────────────────────────────────────────────────────────

SERVICES = [
    {
        "slug": "image-annotation",
        "name": "Image Annotation",
        "nav": "Image annotation",
        "icon": "scan",
        "tone": _tone("lime"),
        "project_type": "Image annotation",
        "visual": "image",
        "short": "Bounding boxes, polygons, segmentation masks and keypoints for still images.",
        "title": "Image Annotation Services — Boxes, Polygons & Masks",
        "meta": (
            "Image annotation services: bounding boxes, polygons, semantic and instance segmentation, keypoints, "
            "cuboids and classification — delivered by trained teams with multi-layer QA."
        ),
        "h1": "Image Annotation Services",
        "lead": (
            "Precise bounding boxes, polygons, segmentation masks and keypoints — produced by trained annotators "
            "and checked through a layered review and QA process before delivery."
        ),
        "intro": (
            "Image annotation is the foundation of most computer vision datasets. Our teams label every relevant "
            "object according to your guideline, apply the agreed class taxonomy and attributes, and pass each "
            "batch through review and QA so the labels your model learns from are complete and consistent."
        ),
        "tags": ["Bounding boxes", "Polygons", "Segmentation", "Keypoints"],
        "includes": [
            ("Bounding boxes", "Tight 2D boxes around every target object, with class labels and attributes such as occlusion or truncation.", "box-select"),
            ("Polygon annotation", "Vertex-by-vertex outlines for irregular shapes where a box would include too much background.", "pentagon"),
            ("Semantic segmentation", "Every pixel assigned to a class — road, product, background — for scene-level understanding.", "layers"),
            ("Instance segmentation", "A separate mask for each individual object, so overlapping items of the same class stay distinct.", "shapes"),
            ("Keypoints", "Points placed on defined landmarks — body joints, hand joints, object corners — following your skeleton.", "waypoints"),
            ("Landmark annotation", "Fine-grained points on faces, products or parts where positional consistency matters.", "crosshair"),
            ("Cuboids", "3D-style cuboids on 2D images to capture object orientation and approximate extent.", "cuboid"),
            ("Classification", "Image-level single- or multi-label classes for filtering, categorising and dataset curation.", "tags"),
            ("Object detection", "Complete detection labels — every relevant instance found, boxed and classified.", "scan-search"),
            ("Image tagging", "Descriptive attribute tags (colour, state, condition) attached to images or objects.", "tag"),
        ],
        "use_cases": [
            "Object detection model training and evaluation",
            "Retail product, packaging and shelf recognition",
            "Manufacturing defect and quality inspection",
            "Crop, plant and fruit detection in agriculture",
            "Robotics perception, grasp points and part keypoints",
            "Medical image annotation following expert-provided guidelines",
        ],
        "qa": [
            "Box tightness and boundary accuracy",
            "Correct class and attributes per object",
            "Missing-object sweeps on every image",
            "Polygon vertex and mask edge quality",
            "Keypoint order and visibility flags",
            "Guideline compliance on documented edge cases",
        ],
        "formats": ["COCO JSON", "YOLO TXT", "Pascal VOC XML", "PNG masks", "CSV", "Custom formats"],
        "faqs": [
            ("Can one project combine several image annotation types?",
             "Yes. Many projects mix types — for example boxes for detection plus keypoints or masks for a subset of "
             "classes. We set up one label schema, agree it with you during the pilot and train the team on it."),
            ("Can you work inside our labeling tool?", TOOLS_STATEMENT + " If you don't have one, we can propose a setup during the requirement review."),
            ("How do you handle occluded, truncated or ambiguous objects?",
             "Edge cases are captured in a shared guideline log during the pilot. Reviewers apply the agreed rule "
             "consistently, and genuinely new cases are escalated to you instead of being guessed."),
            ("Which output formats can you deliver?",
             "Common choices are COCO JSON, YOLO TXT, Pascal VOC XML and PNG masks. " + FORMATS_NOTE),
        ],
        "related": ["video-annotation", "ocr-document-annotation", "action-activity-annotation"],
        "seo": ["image-annotation-services", "computer-vision-annotation", "data-labeling-services"],
    },
    {
        "slug": "video-annotation",
        "name": "Video Annotation",
        "nav": "Video annotation",
        "icon": "clapperboard",
        "tone": _tone("cyan"),
        "project_type": "Video annotation",
        "visual": "video",
        "short": "Object tracking, temporal segmentation and frame-by-frame labels for video.",
        "title": "Video Annotation Services — Tracking & Temporal Labels",
        "meta": (
            "Video annotation services: object and multi-object tracking, video and action segmentation, temporal "
            "and frame-by-frame annotation, event detection and human activity labels with layered QA."
        ),
        "h1": "Video Annotation Services",
        "lead": (
            "Object tracking, temporal segmentation and frame-by-frame labels for video datasets — with consistent "
            "IDs across frames and review at every stage."
        ),
        "intro": (
            "Video adds time to every label. Objects must keep the same identity across frames, segments must start "
            "and end on the right frame, and events need consistent definitions across thousands of clips. Our "
            "teams are trained specifically for temporal work, and reviewers check continuity, not just single frames."
        ),
        "tags": ["Tracking", "Video segmentation", "Temporal labels", "Events"],
        "includes": [
            ("Video segmentation", "Splitting long recordings into meaningful segments with precise start and end frames.", "split"),
            ("Action segmentation", "Labelling each action on the timeline so every frame belongs to the correct step.", "chart-gantt"),
            ("Object tracking", "Following an object across frames with a persistent ID and boxes or masks per frame.", "route"),
            ("Multi-object tracking", "Many objects tracked at once, each keeping its own ID through occlusions and re-entries.", "waypoints"),
            ("Action recognition", "Clip- or segment-level action classes from your taxonomy.", "activity"),
            ("Temporal annotation", "Timestamps, intervals and states that change over time.", "clock-3"),
            ("Frame-by-frame annotation", "Full per-frame labels where interpolation is not accurate enough.", "film"),
            ("Event detection", "Marking when defined events start and end — falls, entries, hand-offs, incidents.", "flag"),
            ("Human activity annotation", "Labelling what people are doing, alone or in groups, across the clip.", "person-standing"),
        ],
        "use_cases": [
            "Autonomous systems and driving scenes",
            "Security and surveillance analytics",
            "Sports player tracking and event tagging",
            "Retail store and customer-flow analytics",
            "Robotics and egocentric (first-person) video",
            "Manufacturing process and workstation monitoring",
        ],
        "qa": [
            "Track ID consistency across frames",
            "Start and end frame accuracy of every segment",
            "Interpolation drift between keyframes",
            "Missing, duplicate or broken tracks",
            "Label consistency across clips and annotators",
            "Guideline compliance on occlusion and re-entry",
        ],
        "formats": ["MOT-style CSV", "COCO-style JSON", "CVAT XML", "Per-frame / per-segment JSON", "KITTI", "Custom formats"],
        "faqs": [
            ("Do you annotate every frame or use interpolation?",
             "Both. Where motion is predictable we annotate keyframes and interpolate, then reviewers check for drift. "
             "Where accuracy requires it, we annotate frame by frame. The approach is agreed per project."),
            ("How do you keep object IDs consistent?",
             "Annotators follow explicit ID rules for occlusion, exits and re-entries, and reviewers play tracks back "
             "end to end to catch swapped or broken IDs before QA."),
            ("Can you work with long recordings?",
             "Yes. Long videos are usually split into manageable clips with overlap rules so that segments and tracks "
             "stay continuous across clip boundaries."),
            ("Which video formats and outputs do you support?",
             "We work with the files and tools you use. " + FORMATS_NOTE),
        ],
        "related": ["action-activity-annotation", "action-description", "image-annotation"],
        "seo": ["video-annotation-services", "video-segmentation", "computer-vision-annotation"],
    },
    {
        "slug": "action-activity-annotation",
        "name": "Action & Activity Annotation",
        "nav": "Action & activity",
        "icon": "hand",
        "tone": _tone("amber"),
        "project_type": "Action & activity annotation",
        "visual": "action",
        "badge": "Current major project area",
        "short": "Hand movements, object interactions and human actions segmented on the timeline.",
        "title": "Action & Activity Annotation for Video Datasets",
        "meta": (
            "Action and activity annotation for video: hand movement, object interaction, pick up / put down, "
            "open / close, move / place, human actions and action-based video segmentation."
        ),
        "h1": "Action & Activity Annotation",
        "lead": (
            "We annotate what people do in video — hand movements, object interactions and complete activities — "
            "segmented into clean, consistently labelled action clips."
        ),
        "intro": (
            "Action annotation is one of our core areas and a current major project focus. It needs more than "
            "drawing skills: annotators must decide exactly when a grasp starts, which hand performs it and which "
            "object is involved — and make that decision the same way every time. Our training, tests and daily "
            "feedback are built around exactly these judgements."
        ),
        "tags": ["Hand movement", "Object interaction", "Pick up / put down", "Action clips"],
        "includes": [
            ("Hand movement", "Left, right or both hands — when they move, reach, hold and release.", "hand"),
            ("Object interaction", "Which object is touched, held, moved or used, and by which hand.", "grab"),
            ("Pick up", "The exact frames where an object leaves its support in the hand.", "arrow-up"),
            ("Put down", "The frames where an object is released onto a surface.", "arrow-down"),
            ("Open / close", "Doors, drawers, lids, containers and devices being opened or closed.", "box"),
            ("Move / place", "Objects carried, repositioned or placed at a target location.", "move"),
            ("Human actions", "Body-level actions such as walking, bending, reaching or turning.", "person-standing"),
            ("Activity recognition", "Higher-level activities composed of several actions — e.g. preparing a drink.", "activity"),
            ("Action-based video segmentation", "Videos cut into action clips with clean boundaries and labels.", "chart-gantt"),
        ],
        "use_cases": [
            "Robot learning from human demonstrations",
            "Egocentric (first-person) video datasets",
            "Human-object interaction research",
            "Assembly, workstation and task-step analysis",
            "Household and kitchen task datasets",
            "Sports and fitness movement analysis",
        ],
        "qa": [
            "Action start / end on the correct frames",
            "Correct hand attribution (left / right / both)",
            "Object identity matches the interaction",
            "No unintended gaps or overlaps between segments",
            "Consistent verb vocabulary across the dataset",
            "Action transitions handled per guideline",
        ],
        "formats": ["Segment JSON", "CSV (start, end, label)", "CVAT XML", "Custom formats"],
        "faqs": [
            ("How do you define the start and end of an action?",
             "We agree boundary rules with you during the pilot — for example, a 'pick up' starts when the hand "
             "closes on the object and ends when the object is clear of the surface — and document them with "
             "frame examples so every annotator applies the same rule."),
            ("Can you annotate egocentric (head-mounted) video?",
             "Yes. First-person footage is common in action datasets. Guidelines cover camera motion, partially "
             "visible hands and objects entering or leaving the frame."),
            ("Can action labels be combined with descriptions or keypoints?",
             "Yes. Action segments are often paired with Hand + Action + Object descriptions, object boxes or hand "
             "keypoints in the same project."),
            ("How is consistency checked across a large team?",
             "Reviewers check every batch, QA samples across annotators, and recurring issues go into daily feedback "
             "and short refresher training."),
        ],
        "related": ["action-description", "video-annotation", "image-annotation"],
        "seo": ["human-activity-annotation", "action-recognition-dataset", "robotic-task-annotation"],
    },
    {
        "slug": "action-description",
        "name": "Action Description",
        "nav": "Action description",
        "icon": "message-square-text",
        "tone": _tone("violet"),
        "project_type": "Action description",
        "visual": "description",
        "short": "Structured Hand + Action + Object descriptions aligned to each action segment.",
        "title": "Action Description Annotation — Hand + Action + Object",
        "meta": (
            "Structured action descriptions for video datasets: Hand + Action + Object sentences such as "
            "“Right hand picks up a cup.”, aligned to segments, with consistency rules and description QA."
        ),
        "h1": "Action Description Annotation",
        "lead": (
            "Short, structured descriptions written for each action segment — following a Hand + Action + Object "
            "pattern so every clip in your dataset is described the same way."
        ),
        "intro": (
            "Free-text descriptions drift quickly: different words for the same action, different levels of detail, "
            "guesses about unclear objects. We write descriptions against a fixed structure and an agreed vocabulary, "
            "align each sentence to its action segment, and review descriptions with the same rigour as visual labels."
        ),
        "example": "Right hand picks up a cup.",
        "tags": ["Hand + Action + Object", "Segment-aligned", "Controlled vocabulary"],
        "includes": [
            ("Structured video descriptions", "One clear sentence per action, written to a fixed pattern.", "message-square-text"),
            ("Hand + Action + Object format", "Who acts, what they do, and what they act on — e.g. “Left hand opens the drawer.”", "list-tree"),
            ("Segment-aligned text", "Every description is tied to the start and end of its action segment.", "chart-gantt"),
            ("Controlled vocabulary", "Approved verbs and object names, so the same action is always described the same way.", "tags"),
            ("Multi-step narration", "Sequences of actions described in order for longer tasks.", "list-ordered"),
            ("Description QA & correction", "Reviewers check accuracy, wording and alignment; errors are corrected before delivery.", "clipboard-check"),
        ],
        "rules": [
            "Name the hand explicitly: Left hand, Right hand or Both hands",
            "One action per sentence, in the present tense",
            "Use verbs from the approved list — picks up, puts down, opens, closes, moves, places",
            "Name objects consistently across the whole dataset",
            "The sentence must match the segment's start and end",
            "No guessing — unclear objects are flagged, not invented",
        ],
        "use_cases": [
            "Vision-language and video-captioning datasets",
            "Robot learning from narrated demonstrations",
            "Instruction-following and task-planning research",
            "Searchable, text-indexed video archives",
            "Evaluation sets for video understanding",
        ],
        "qa": [
            "Hand, action and object match the video",
            "Verbs from the approved vocabulary only",
            "Format and grammar consistency",
            "Alignment with segment boundaries",
            "Consistent object naming across clips",
            "Unclear cases flagged rather than guessed",
        ],
        "formats": ["Segment JSON (start, end, text)", "CSV", "JSONL", "Custom formats"],
        "faqs": [
            ("What does a Hand + Action + Object description look like?",
             "A short present-tense sentence such as “Right hand picks up a cup.” or “Left hand closes the drawer.” "
             "The hand, the verb and the object each come from an agreed list."),
            ("Can you follow our own description template?",
             "Yes. If you already have a template or vocabulary, we adopt it and document any edge cases with you "
             "during the pilot."),
            ("How do you keep wording consistent across annotators?",
             "A controlled vocabulary, written examples for every verb, reviewer checks on every batch and daily "
             "feedback on recurring wording issues."),
            ("Do descriptions come with time segments?",
             "Usually yes — each description is aligned to the start and end frame of its action segment. "
             + FORMATS_NOTE),
        ],
        "related": ["action-activity-annotation", "video-annotation", "text-annotation"],
        "seo": ["action-recognition-dataset", "human-activity-annotation", "robotic-task-annotation"],
    },
    {
        "slug": "text-annotation",
        "name": "Text Annotation",
        "nav": "Text annotation",
        "icon": "text-select",
        "tone": _tone("pink"),
        "project_type": "Text annotation",
        "visual": "text",
        "short": "Classification, intent, entities and sentiment for NLP datasets.",
        "title": "Text Annotation Services — Intent, NER & Sentiment",
        "meta": (
            "Text annotation services: text and intent classification, named entity annotation, sentiment "
            "annotation, categorisation and NLP dataset preparation with structured QA."
        ),
        "h1": "Text Annotation Services",
        "lead": (
            "Classification, intent, entity and sentiment labels for NLP datasets — applied consistently against "
            "your taxonomy and reviewed before delivery."
        ),
        "intro": (
            "Text labels look simple until two annotators disagree. We start from a clear taxonomy with examples, "
            "measure agreement during the pilot, and refine definitions until the team labels the same text the "
            "same way."
        ),
        "tags": ["Classification", "Intent", "Entities (NER)", "Sentiment"],
        "includes": [
            ("Text classification", "Assigning one or more categories to documents, messages or sentences.", "tags"),
            ("Intent classification", "Labelling what a user wants — for assistants, chatbots and support routing.", "message-square"),
            ("Entity annotation", "Marking spans such as names, products, dates, amounts and locations.", "highlighter"),
            ("Sentiment annotation", "Positive, negative, neutral or fine-grained sentiment, at document or aspect level.", "thumbs-up"),
            ("Text categorisation", "Topic and content categories for search, moderation and organisation.", "folder"),
            ("NLP dataset preparation", "Cleaning, de-duplicating and structuring text into the format your pipeline expects.", "file-json"),
        ],
        "use_cases": [
            "Chatbot and virtual assistant training",
            "Customer support ticket routing",
            "Search and content categorisation",
            "Review and feedback analysis",
            "Information extraction from text",
            "Evaluation sets for language models",
        ],
        "qa": [
            "Entity span boundaries",
            "Taxonomy and intent-definition compliance",
            "Sentiment consistency across annotators",
            "Agreement checks on sampled items",
            "Duplicate and near-duplicate detection",
            "Guideline compliance on ambiguous text",
        ],
        "formats": ["JSON / JSONL", "CSV", "BIO / IOB tags", "XML", "Custom formats"],
        "faqs": [
            ("Which languages do you annotate?",
             "Language coverage depends on the project and the team assigned. Tell us the languages and volume in "
             "your request and we will confirm what we can staff."),
            ("Can you work with our existing taxonomy?",
             "Yes. We use your categories and definitions, and suggest clarifications where the pilot shows "
             "annotators interpreting a label differently."),
            ("How do you measure consistency?",
             "During the pilot we double-annotate a sample and review disagreements. In production, QA samples each "
             "batch and recurring issues go into daily feedback."),
        ],
        "related": ["ocr-document-annotation", "action-description", "image-annotation"],
        "seo": ["data-labeling-services", "ai-training-data", "ai-data-annotation-services"],
    },
    {
        "slug": "ocr-document-annotation",
        "name": "OCR & Document Annotation",
        "nav": "OCR & documents",
        "icon": "scan-text",
        "tone": _tone("brand"),
        "project_type": "OCR / document annotation",
        "visual": "ocr",
        "short": "Text detection, transcription, layout and form labels for document AI.",
        "title": "OCR & Document Annotation Services",
        "meta": (
            "OCR and document annotation: text detection, OCR transcription, document structure and layout, "
            "form and key-value labeling and handwritten text annotation with QA."
        ),
        "h1": "OCR & Document Annotation",
        "lead": (
            "Text regions, transcriptions, document structure and form fields — annotated precisely for OCR and "
            "document understanding datasets."
        ),
        "intro": (
            "Document datasets combine geometry and language: a region must be boxed tightly, transcribed exactly "
            "and linked to the right field. Our annotators work to character-level transcription rules and "
            "reviewers check both the box and the text."
        ),
        "tags": ["Text detection", "Transcription", "Layout", "Key-value fields"],
        "includes": [
            ("Text detection", "Word-, line- or block-level boxes and polygons around text regions.", "scan-text"),
            ("OCR annotation", "Exact transcription of each text region following your character rules.", "type"),
            ("Document structure annotation", "Headers, paragraphs, tables, figures and reading order.", "layout-grid"),
            ("Form / document labeling", "Key-value pairs and field types on forms, invoices and receipts.", "clipboard-list"),
            ("Handwritten text annotation", "Transcribing handwriting, with uncertain characters flagged per guideline.", "signature"),
            ("Table annotation", "Table, row, column and cell regions for structured extraction.", "table"),
        ],
        "use_cases": [
            "Invoices, receipts and purchase orders",
            "Forms and application documents",
            "Scanned archives and handwritten notes",
            "Logistics labels and shipping documents",
            "Scene text on signs, packaging and labels",
            "Document layout analysis",
        ],
        "qa": [
            "Character-level transcription accuracy",
            "Text region boundary accuracy",
            "Correct key-value and field linking",
            "Reading order",
            "Uncertain handwriting flagged, not guessed",
            "Sensitive fields handled per client rules",
        ],
        "formats": ["JSON", "COCO-style JSON", "XML", "CSV", "Custom formats"],
        "faqs": [
            ("Do you transcribe handwriting?",
             "Yes, following your transcription rules. Illegible or uncertain characters are flagged with an agreed "
             "marker rather than guessed."),
            ("Can you label documents that contain personal data?",
             "Documents with personal data are handled under the confidentiality controls agreed for the project — "
             "project-specific access, controlled accounts and NDAs where required. See our Security page."),
            ("Which output structure do you deliver?",
             "Typically JSON with region geometry, text and field type. " + FORMATS_NOTE),
        ],
        "related": ["text-annotation", "image-annotation", "video-annotation"],
        "seo": ["data-labeling-services", "ai-training-data", "computer-vision-annotation"],
    },
]

for _s in SERVICES:  # lower-case name for use mid-sentence ("Start your image annotation project")
    _s["name_lc"] = _s["name"].lower().replace("ocr", "OCR")

SERVICE_BY_SLUG = {s["slug"]: s for s in SERVICES}

# ─── Annotation types / modalities (capability strip, quote form) ───────────

MODALITIES = [
    {"name": "Image", "icon": "image", "items": ["Boxes", "Polygons", "Masks", "Keypoints"]},
    {"name": "Video", "icon": "clapperboard", "items": ["Tracking", "Segmentation", "Events"]},
    {"name": "Action", "icon": "hand", "items": ["Hand movement", "Interactions", "Clips"]},
    {"name": "Text", "icon": "text-select", "items": ["Intent", "Entities", "Sentiment"]},
    {"name": "Documents", "icon": "scan-text", "items": ["OCR", "Layout", "Forms"]},
    {"name": "Multimodal", "icon": "layers", "items": ["Video + text", "Image + text"]},
]

ANNOTATION_TYPES = [
    "Bounding boxes", "Polygons", "Semantic segmentation", "Instance segmentation", "Keypoints / landmarks",
    "Cuboids", "Classification / tagging", "Object tracking", "Video segmentation", "Action segmentation",
    "Action recognition", "Hand / object interaction", "Action description", "Text classification / intent",
    "Entities (NER)", "Sentiment", "OCR / transcription", "Document structure / forms",
]

# ─── Specialisation: human action & video understanding ─────────────────────

SPECIALIZATION = [
    ("Video segmentation", "Long recordings cut into precise, labelled segments.", "split"),
    ("Action-based clips", "Clips that contain exactly one action, start to finish.", "film"),
    ("Hand movement", "Left / right hand reach, grasp, hold and release.", "hand"),
    ("Object interaction", "Which object is touched, moved or used — and by which hand.", "grab"),
    ("Action transitions", "Clean boundaries where one action ends and the next begins.", "git-commit-horizontal"),
    ("Action descriptions", "Structured sentences aligned to each action segment.", "message-square-text"),
    ("Hand + Action + Object", "“Right hand picks up a cup.” — one pattern, every clip.", "list-tree"),
    ("Video QA", "Reviewers replay segments to verify timing and labels.", "circle-play"),
    ("Annotation review", "Every batch reviewed before it reaches QA.", "eye"),
    ("Quality control", "Final QA, correction and validation before delivery.", "shield-check"),
]

ACTION_SEGMENTS = [
    {"label": "reach", "hand": "Right hand", "verb": "reaches for", "object": "the cup", "span": 3, "tone": _tone("violet")},
    {"label": "grasp", "hand": "Right hand", "verb": "grasps", "object": "the cup", "span": 2, "tone": _tone("cyan")},
    {"label": "pick up", "hand": "Right hand", "verb": "picks up", "object": "a cup", "span": 4, "tone": _tone("lime")},
    {"label": "place", "hand": "Right hand", "verb": "places", "object": "the cup on the tray", "span": 3, "tone": _tone("amber")},
]

# ─── Computer-vision solutions (Solutions page) ─────────────────────────────

CV_SOLUTIONS = [
    {
        "slug": "object-detection",
        "name": "Object Detection",
        "icon": "scan-search",
        "visual": "detection",
        "tone": _tone("lime"),
        "summary": "Detection models learn to find and classify objects. They need every relevant instance boxed tightly, with the correct class.",
        "annotation": ["Bounding boxes", "Class labels & attributes", "Cuboids", "Hard-negative review"],
        "models": ["YOLO", "Faster R-CNN", "SSD", "RT-DETR", "Other architectures"],
    },
    {
        "slug": "image-segmentation",
        "name": "Image Segmentation",
        "icon": "shapes",
        "visual": "segmentation",
        "tone": _tone("pink"),
        "summary": "Segmentation models predict object shapes pixel by pixel, so masks must follow true object boundaries.",
        "annotation": ["Semantic masks", "Instance masks", "Polygons", "Mask review & refinement"],
        "models": ["Semantic segmentation", "Instance segmentation", "Mask-based models", "SAM-style segmentation workflows"],
    },
    {
        "slug": "pose-keypoints",
        "name": "Pose / Keypoint Estimation",
        "icon": "person-standing",
        "visual": "pose",
        "tone": _tone("violet"),
        "summary": "Pose models learn the position of defined points. Keypoints must follow a fixed order, skeleton and visibility rules.",
        "annotation": ["Body keypoints", "Hand keypoints", "Object keypoints", "Visibility & occlusion flags"],
        "models": ["Human pose", "Hand keypoints", "Body keypoints", "Object keypoints", "Robotic keypoints"],
    },
    {
        "slug": "object-tracking",
        "name": "Object Tracking",
        "icon": "route",
        "visual": "tracking",
        "tone": _tone("cyan"),
        "summary": "Tracking models follow objects through time. Labels need persistent IDs through occlusion, exits and re-entries.",
        "annotation": ["Per-frame boxes or masks", "Persistent track IDs", "Occlusion states", "Interpolation review"],
        "models": ["MOT", "Multi-object tracking", "Single-object tracking", "Video object tracking"],
    },
    {
        "slug": "action-recognition",
        "name": "Action Recognition",
        "icon": "activity",
        "visual": "action",
        "tone": _tone("amber"),
        "summary": "Action models learn what is happening and when. They need consistent action classes and precise temporal boundaries.",
        "annotation": ["Action classes", "Temporal segments", "Hand / object interactions", "Action descriptions"],
        "models": ["Human activity recognition", "Action detection", "Temporal action segmentation"],
    },
]

# ─── SEO landing pages (/solutions/<slug>/) ──────────────────────────────────

SOLUTION_PAGES = [
    {
        "slug": "ai-data-annotation-services",
        "name": "AI Data Annotation Services",
        "icon": "sparkles",
        "visual": "workspace",
        "project_type": "",
        "title": "AI Data Annotation Services — Image, Video & Text",
        "meta": (
            "Outsource AI data annotation to a structured team: image, video, action, text and document annotation "
            "with layered review and QA, delivered in the format your pipeline needs."
        ),
        "h1": "AI Data Annotation Services",
        "eyebrow": "Annotation for AI teams",
        "lead": (
            "Image, video, action, text and document annotation delivered by trained teams, structured workflows "
            "and dedicated quality control."
        ),
        "intro": [
            "Every supervised model is only as reliable as the labels it learns from. Inconsistent boxes, missed "
            "objects or vague action boundaries become errors your model repeats. Our job is to remove that noise.",
            DATASET_STATEMENT + " We work on the data you provide, follow your guidelines, and deliver labels "
            "that have passed review, QA and correction.",
        ],
        "deliver": [
            ("Image annotation", "Boxes, polygons, semantic and instance masks, keypoints, cuboids and classification."),
            ("Video annotation", "Tracking, video segmentation, temporal labels and event detection."),
            ("Action & activity annotation", "Hand movements, object interactions and action-based clips."),
            ("Action descriptions", "Structured Hand + Action + Object sentences aligned to segments."),
            ("Text annotation", "Classification, intent, entities and sentiment for NLP datasets."),
            ("OCR & document annotation", "Text regions, transcriptions, layout and form fields."),
        ],
        "process": [
            "You share guidelines, examples and the expected output.",
            "We run a pilot so you can check quality before production.",
            "A trained team with reviewers and QA is assigned to your project.",
            "Production runs through annotation, review, QA and correction.",
            "You receive a validated dataset in the agreed format.",
        ],
        "qa": ["Annotation accuracy", "Label consistency", "Missing annotation detection", "Duplicate / error detection", "Guideline compliance"],
        "formats": ["YOLO", "COCO", "Pascal VOC", "JSON", "CSV", "XML", "Masks", "Custom formats"],
        "faqs": [
            ("What makes your annotation service different from crowdsourcing?",
             "Your project is handled by a dedicated, trained team with team leads, reviewers and QA members — not an "
             "anonymous crowd. The same people build up project knowledge, and every batch passes review and QA."),
            ("Do you build or train AI models?", "No. " + DATASET_STATEMENT),
            ("How quickly can a project start?",
             "After the requirement review we usually propose a pilot task first. Production timing depends on volume, "
             "complexity and team setup, and is agreed with you before work starts."),
        ],
        "related_services": ["image-annotation", "video-annotation", "action-activity-annotation"],
        "related_pages": ["data-labeling-services", "computer-vision-annotation", "ai-training-data"],
    },
    {
        "slug": "video-annotation-services",
        "name": "Video Annotation Services",
        "icon": "clapperboard",
        "visual": "video",
        "project_type": "Video annotation",
        "title": "Outsource Video Annotation — Tracking & Action Labels",
        "meta": (
            "Outsource video annotation to a trained team: object tracking, video segmentation, action and event "
            "labels with frame-accurate review. Learn how we scope and deliver video projects."
        ),
        "h1": "Video Annotation Services",
        "eyebrow": "Outsourced video labeling",
        "lead": (
            "A practical guide to outsourcing video annotation — what to prepare, how we scope the work and how "
            "quality is controlled across thousands of frames."
        ),
        "intro": [
            "Video projects are where annotation quality is hardest to maintain. Labels must stay correct over time: "
            "IDs must persist, segments must start on the right frame and definitions must hold across every clip.",
            "We scope video projects around those risks. Before production we agree frame-level rules with you, test "
            "them in a pilot, and only then scale the team.",
        ],
        "deliver": [
            ("Object & multi-object tracking", "Persistent IDs with per-frame boxes or masks."),
            ("Video segmentation", "Recordings split into labelled segments with precise boundaries."),
            ("Action & event labels", "When actions and events start, end and what they are."),
            ("Frame-by-frame annotation", "Full per-frame labels where interpolation is not enough."),
            ("Human activity annotation", "What people are doing, individually or in groups."),
            ("Video QA", "Reviewers replay tracks and segments end to end before delivery."),
        ],
        "process": [
            "Share sample clips, your label list and any existing guideline.",
            "We agree frame rules: boundaries, occlusion, re-entry and clip overlaps.",
            "A pilot batch is annotated, reviewed and sent for your feedback.",
            "The team scales to your volume with reviewers and QA in place.",
            "Validated annotations are delivered per batch in your format.",
        ],
        "qa": ["Track ID consistency", "Segment boundary accuracy", "Interpolation drift", "Missing / duplicate tracks", "Label consistency"],
        "formats": ["MOT-style CSV", "COCO-style JSON", "CVAT XML", "KITTI", "JSON", "Custom formats"],
        "faqs": [
            ("What should I send to get a video annotation quote?",
             "A few representative clips, your label list or guideline, the expected output format, and an estimate "
             "of total hours or clips. If you don't have a guideline yet, we can help draft one during the pilot."),
            ("How is video annotation usually priced?",
             "It depends on label density, frame rate, annotation type and QA depth, so we quote after reviewing "
             "samples — often after a short pilot."),
            ("Can you annotate in our own video tool?", TOOLS_STATEMENT),
        ],
        "related_services": ["video-annotation", "action-activity-annotation", "action-description"],
        "related_pages": ["video-segmentation", "human-activity-annotation", "action-recognition-dataset"],
    },
    {
        "slug": "image-annotation-services",
        "name": "Image Annotation Services",
        "icon": "scan",
        "visual": "image",
        "project_type": "Image annotation",
        "title": "Outsource Image Annotation — Boxes, Polygons & Masks",
        "meta": (
            "Outsource image annotation to a dedicated team: bounding boxes, polygons, segmentation masks, "
            "keypoints and classification, with pilot-first onboarding and layered QA."
        ),
        "h1": "Image Annotation Services",
        "eyebrow": "Outsourced image labeling",
        "lead": (
            "How to get consistent, complete image labels at volume — and what a structured annotation partner "
            "should do before, during and after production."
        ),
        "intro": [
            "Most image annotation problems are not about drawing — they are about decisions. Is a half-visible "
            "object labelled? Where does a reflection end? Which class does a borderline item belong to?",
            "We make those decisions explicit. During the pilot we document edge cases with you, then train the team "
            "on them, so the 10,000th image is labelled with the same rules as the first.",
        ],
        "deliver": [
            ("Bounding boxes", "Tight, complete boxes with classes and attributes."),
            ("Polygons & masks", "Semantic and instance segmentation along true boundaries."),
            ("Keypoints & landmarks", "Skeletons and points in a fixed order with visibility flags."),
            ("Cuboids", "Orientation-aware cuboids on 2D images."),
            ("Classification & tagging", "Image-level and object-level labels and attributes."),
            ("Dataset clean-up", "Fixing or re-labelling existing annotations against a new guideline."),
        ],
        "process": [
            "Share sample images, classes and the expected output.",
            "We document edge cases and run a pilot batch.",
            "Annotators are trained and tested on your guideline.",
            "Every batch is reviewed and QA-sampled before release.",
            "Validated labels are delivered in your format.",
        ],
        "qa": ["Box tightness", "Correct classes", "Missing-object sweeps", "Mask edge quality", "Keypoint order"],
        "formats": ["COCO JSON", "YOLO TXT", "Pascal VOC XML", "PNG masks", "CSV", "Custom formats"],
        "faqs": [
            ("Can you fix an existing dataset rather than start from scratch?",
             "Yes. We can review and correct existing labels against an updated guideline — useful when a model "
             "plateaus because of label noise."),
            ("Do you use pre-labels from our model?",
             "If you provide model pre-labels, annotators correct them rather than drawing from scratch. Every "
             "pre-label is still reviewed by a person."),
            ("What image volumes can you handle?", SCALE_STATEMENT),
        ],
        "related_services": ["image-annotation", "ocr-document-annotation", "video-annotation"],
        "related_pages": ["computer-vision-annotation", "data-labeling-services", "ai-data-annotation-services"],
    },
    {
        "slug": "video-segmentation",
        "name": "Video Segmentation",
        "icon": "split",
        "visual": "timeline",
        "project_type": "Video annotation",
        "title": "Video Segmentation Annotation — Temporal & Action Segments",
        "meta": (
            "Video segmentation annotation: temporal segments, action-based clips and frame-accurate boundaries for "
            "action recognition and video understanding datasets."
        ),
        "h1": "Video Segmentation Annotation",
        "eyebrow": "Temporal segmentation",
        "lead": (
            "Long recordings divided into precise, labelled segments — so every frame belongs to the right action, "
            "step or event."
        ),
        "intro": [
            "Temporal video segmentation answers a simple question for every frame: what is happening right now? "
            "For training data, the hard part is the boundary — the exact frame where one action ends and the "
            "next begins.",
            "We define boundary rules with you, show annotators frame-level examples, and have reviewers replay every "
            "transition. Where the task requires it, segments are paired with object masks, tracks or descriptions.",
        ],
        "deliver": [
            ("Temporal segments", "Start frame, end frame and label for each segment."),
            ("Action-based clips", "Recordings cut so that each clip holds exactly one action."),
            ("Step segmentation", "Multi-step tasks divided into ordered steps."),
            ("Idle / background segments", "Explicit labels for frames where no target action happens."),
            ("Segment descriptions", "Optional Hand + Action + Object sentence per segment."),
            ("Pixel-level video masks", "Object masks across frames where spatial segmentation is also required."),
        ],
        "process": [
            "Agree the action list and boundary rules with frame examples.",
            "Pilot a set of recordings and review transitions with you.",
            "Train the team on boundary decisions and test them.",
            "Review replays every transition; QA samples across annotators.",
            "Deliver segments as JSON / CSV in your structure.",
        ],
        "qa": ["Boundary frame accuracy", "No unintended gaps / overlaps", "Correct action labels", "Transition handling", "Guideline compliance"],
        "formats": ["Segment JSON", "CSV (start, end, label)", "CVAT XML", "Custom formats"],
        "faqs": [
            ("What is the difference between video segmentation and action segmentation?",
             "Video segmentation is the general task of splitting a video into meaningful segments; action "
             "segmentation is the specific case where each segment is an action. The term is also used for "
             "pixel-level masks in video — we support both."),
            ("How precise are segment boundaries?",
             "Boundaries are set to the frame according to agreed rules, and reviewers check every transition. "
             "The rules — not guesswork — define where an action starts and ends."),
            ("Can segments overlap?", "If your schema allows parallel actions (for example two hands doing different things), yes. Otherwise we enforce non-overlapping segments."),
        ],
        "related_services": ["video-annotation", "action-activity-annotation", "action-description"],
        "related_pages": ["action-recognition-dataset", "human-activity-annotation", "video-annotation-services"],
    },
    {
        "slug": "action-recognition-dataset",
        "name": "Action Recognition Datasets",
        "icon": "activity",
        "visual": "action",
        "project_type": "Action & activity annotation",
        "title": "Action Recognition Dataset Annotation",
        "meta": (
            "Annotation for action recognition datasets: action classes, temporal segments, hand-object "
            "interactions and structured descriptions, with consistency-focused QA."
        ),
        "h1": "Action Recognition Dataset Annotation",
        "eyebrow": "Datasets for action models",
        "lead": (
            "Consistent action classes, precise temporal boundaries and hand-object detail — the labels action "
            "recognition models actually depend on."
        ),
        "intro": [
            "Action recognition datasets fail in subtle ways: two annotators call the same motion different things, "
            "boundaries shift by a few frames, or the acting hand is ignored. Models trained on that data learn the "
            "inconsistency.",
            "Action annotation is one of our core areas. We build a controlled action vocabulary with you, train "
            "annotators on boundary decisions and review every segment for label and timing accuracy.",
        ],
        "deliver": [
            ("Action classes", "Clip- or segment-level labels from your taxonomy."),
            ("Temporal action segments", "Precise start and end frames for every action."),
            ("Hand attribution", "Left, right or both hands for each action."),
            ("Object interaction labels", "Which object is acted on, linked to the action."),
            ("Action descriptions", "Hand + Action + Object sentences, e.g. “Right hand picks up a cup.”"),
            ("Supporting labels", "Object boxes or hand keypoints where the dataset needs them."),
        ],
        "process": [
            "Define the action taxonomy and boundary rules together.",
            "Pilot on representative clips and align on edge cases.",
            "Train and test annotators on your action vocabulary.",
            "Review every segment; QA checks consistency across the team.",
            "Deliver labels and segments in your dataset structure.",
        ],
        "qa": ["Action accuracy", "Boundary accuracy", "Hand / action / object matching", "Vocabulary consistency", "Missing action detection"],
        "formats": ["Segment JSON", "CSV", "JSONL", "Custom formats"],
        "faqs": [
            ("Do you collect the videos for the dataset?",
             "We annotate video you provide or have the rights to use. We focus on annotation, review and QA."),
            ("Can you extend an existing action dataset with new classes?",
             "Yes. We can add classes or descriptions to existing data and re-check older labels against the "
             "updated taxonomy if needed."),
            ("Can you handle fine-grained actions like grasp vs. pick up?",
             "Yes — that is exactly where written boundary rules and frame examples matter. We agree them in the pilot "
             "and enforce them in review."),
        ],
        "related_services": ["action-activity-annotation", "action-description", "video-annotation"],
        "related_pages": ["human-activity-annotation", "video-segmentation", "robotic-task-annotation"],
    },
    {
        "slug": "computer-vision-annotation",
        "name": "Computer Vision Annotation",
        "icon": "scan-eye",
        "visual": "detection",
        "project_type": "",
        "title": "Computer Vision Annotation — Detection, Pose & Tracking",
        "meta": (
            "Computer vision annotation for detection, segmentation, pose estimation, tracking and action "
            "recognition — annotated datasets to support model training, evaluation and improvement."
        ),
        "h1": "Computer Vision Annotation",
        "eyebrow": "Labels for vision models",
        "lead": (
            "Annotation matched to the computer vision task you're training for — detection, segmentation, pose, "
            "tracking or action recognition."
        ),
        "intro": [
            "Different vision tasks need different labels. A detector needs complete, tight boxes; a segmentation "
            "model needs accurate boundaries; a pose model needs keypoints in a fixed order; a tracker needs "
            "persistent IDs.",
            DATASET_STATEMENT + " We start from your target task and output format, and design the annotation "
            "and QA around it.",
        ],
        "deliver": [
            ("Object detection labels", "Boxes and classes for YOLO, Faster R-CNN, SSD, RT-DETR and other architectures."),
            ("Segmentation masks", "Semantic and instance masks, including SAM-style mask review workflows."),
            ("Pose & keypoints", "Human, hand, body, object and robotic keypoints."),
            ("Tracking annotations", "Single- and multi-object tracks with persistent IDs."),
            ("Action labels", "Activity classes and temporal action segments."),
            ("Evaluation sets", "Carefully reviewed hold-out sets for measuring model performance."),
        ],
        "process": [
            "Tell us the task, target classes and output format.",
            "We map your model's needs to an annotation schema.",
            "A pilot batch confirms quality and the format.",
            "Production with review, QA and correction.",
            "Delivery of validated, model-ready annotations.",
        ],
        "qa": ["Object accuracy", "Boundary accuracy", "Keypoint order", "Track continuity", "Guideline compliance"],
        "formats": ["YOLO", "COCO", "Pascal VOC", "KITTI", "Masks", "Custom formats"],
        "faqs": [
            ("Which model architectures do your annotations support?",
             "The labels are model-agnostic: we deliver annotations in the format your training pipeline expects — "
             "for example YOLO or COCO for detectors such as YOLO, Faster R-CNN, SSD or RT-DETR."),
            ("Can you review model predictions instead of labelling from scratch?",
             "Yes. Correcting pre-labels or reviewing model outputs is a common workflow; every item is still checked "
             "by a person."),
            ("Do you build the models?", "No. " + DATASET_STATEMENT),
        ],
        "related_services": ["image-annotation", "video-annotation", "action-activity-annotation"],
        "related_pages": ["image-annotation-services", "video-annotation-services", "ai-training-data"],
    },
    {
        "slug": "data-labeling-services",
        "name": "Data Labeling Services",
        "icon": "tags",
        "visual": "workspace",
        "project_type": "",
        "title": "Data Labeling Services — Managed Teams with Review & QA",
        "meta": (
            "Managed data labeling services: dedicated labeling teams with team leads, reviewers and QA for image, "
            "video, text and document data. Pilot-first onboarding."
        ),
        "h1": "Data Labeling Services",
        "eyebrow": "Managed labeling teams",
        "lead": (
            "A managed labeling team — annotators, team leads, reviewers and QA — working to your guideline and "
            "reporting to one point of contact."
        ),
        "intro": [
            "Data labeling at scale is an operations problem as much as a skills problem. Someone has to train new "
            "annotators, answer guideline questions, catch drift early and keep batches moving.",
            "We provide that structure. Each project has a dedicated team with clear roles, a training and feedback "
            "loop, and a QA layer that is separate from production.",
        ],
        "deliver": [
            ("Dedicated project team", "Annotators assigned to your project, not a rotating crowd."),
            ("Team leads", "Day-to-day coordination and guideline questions."),
            ("Reviewers", "Every batch reviewed before it reaches QA."),
            ("QA members", "Independent quality checks and final validation."),
            ("Training & tests", "Project tutorials, tests and daily feedback for every annotator."),
            ("Regular reporting", "Progress and quality updates in the cadence you need."),
        ],
        "process": [
            "Requirement review: guidelines, examples, expected output.",
            "Pilot task to align on quality.",
            "Team setup with trained annotators and QA members.",
            "Production with annotation, review, QA and correction.",
            "Delivery according to your specification.",
        ],
        "qa": ["Annotation accuracy", "Label consistency", "Guideline compliance", "Missing annotation detection", "Duplicate / error detection"],
        "formats": ["JSON", "CSV", "XML", "COCO", "YOLO", "Custom formats"],
        "faqs": [
            ("Is data labeling the same as data annotation?",
             "In practice the terms are used interchangeably. 'Labeling' is often used for classification-style tasks "
             "and 'annotation' for richer labels such as boxes, masks or segments — we do both."),
            ("Can the team grow with our project?", SCALE_STATEMENT),
            ("Who do we talk to during the project?",
             "You have a single point of contact who coordinates with team leads, reviewers and QA on your behalf."),
        ],
        "related_services": ["image-annotation", "text-annotation", "ocr-document-annotation"],
        "related_pages": ["ai-data-annotation-services", "ai-training-data", "computer-vision-annotation"],
    },
    {
        "slug": "ai-training-data",
        "name": "AI Training Data",
        "icon": "database",
        "visual": "workspace",
        "project_type": "",
        "title": "AI Training Data — Annotated & Validated Datasets",
        "meta": (
            "Turn raw images, video, text and documents into validated AI training data. Annotation, review and QA "
            "to support training, evaluation and improvement of AI models."
        ),
        "h1": "AI Training Data, Annotated and Validated",
        "eyebrow": "From raw data to training data",
        "lead": (
            "We turn the raw data you collect — images, video, text and documents — into annotated, validated "
            "datasets your team can train and evaluate on."
        ),
        "intro": [
            "Raw data rarely becomes training data in one step. It needs a schema, consistent labels, review, "
            "corrections and an export your pipeline can read.",
            DATASET_STATEMENT + " We handle the annotation, review and QA so your engineers can focus on modelling.",
        ],
        "deliver": [
            ("Training sets", "Fully annotated data for model training."),
            ("Validation & test sets", "Extra-reviewed subsets for reliable evaluation."),
            ("Re-annotation", "Existing labels corrected or upgraded to a new schema."),
            ("Edge-case batches", "Targeted labeling of hard or rare cases your model struggles with."),
            ("Pre-label correction", "Human correction of model-generated labels."),
            ("Format conversion", "Delivery in the format your pipeline expects."),
        ],
        "process": [
            "Share data samples, the target task and output format.",
            "We propose an annotation schema and run a pilot.",
            "A trained team is set up with reviewers and QA.",
            "Batches move through annotation, review, QA and correction.",
            "Validated datasets are delivered per batch or milestone.",
        ],
        "qa": ["Annotation accuracy", "Label consistency", "Missing annotation detection", "Duplicate / error detection", "Guideline compliance"],
        "formats": ["YOLO", "COCO", "Pascal VOC", "KITTI", "JSON", "CSV", "XML", "Custom formats"],
        "faqs": [
            ("Do you provide or collect raw data?",
             "We annotate data that you provide or are entitled to use. Our focus is turning that data into validated, "
             "annotated datasets."),
            ("Can you prepare separate evaluation sets?",
             "Yes. Evaluation and test sets can receive additional review passes so that you can trust your metrics."),
            ("How do you deliver large datasets?",
             "Usually in batches or milestones, through your storage, your annotation platform or another transfer "
             "method agreed for the project."),
        ],
        "related_services": ["image-annotation", "video-annotation", "text-annotation"],
        "related_pages": ["ai-data-annotation-services", "data-labeling-services", "computer-vision-annotation"],
    },
    {
        "slug": "human-activity-annotation",
        "name": "Human Activity Annotation",
        "icon": "person-standing",
        "visual": "pose",
        "project_type": "Action & activity annotation",
        "title": "Human Activity Annotation — Actions, Poses & Interactions",
        "meta": (
            "Human activity annotation for video: activity classes, temporal segments, pose keypoints and "
            "human-object interactions for activity recognition datasets."
        ),
        "h1": "Human Activity Annotation",
        "eyebrow": "People in video",
        "lead": (
            "What people are doing, when and with what — annotated as activity classes, segments, poses and "
            "interactions."
        ),
        "intro": [
            "Human activity data appears in robotics, retail analytics, sports, workplace safety and research. The "
            "common need: a consistent definition of each activity and accurate timing.",
            "We combine temporal segmentation with person-level detail — boxes, tracks, keypoints and hand-object "
            "interactions — depending on what your model needs to learn.",
        ],
        "deliver": [
            ("Activity classes", "Clip- or segment-level labels from your taxonomy."),
            ("Temporal segments", "Start and end frames for each activity."),
            ("Person detection & tracking", "Boxes and persistent IDs for each person."),
            ("Pose keypoints", "Body and hand keypoints with visibility flags."),
            ("Human-object interaction", "Which object a person interacts with, and how."),
            ("Group activities", "Activities involving several people at once."),
        ],
        "process": [
            "Agree activity definitions and examples.",
            "Pilot on representative footage.",
            "Train and test the team on activity boundaries.",
            "Review and QA for timing, labels and person IDs.",
            "Deliver annotations in your structure.",
        ],
        "qa": ["Action accuracy", "Boundary accuracy", "Person ID consistency", "Keypoint order", "Guideline compliance"],
        "formats": ["Segment JSON", "COCO keypoints", "MOT-style CSV", "Custom formats"],
        "faqs": [
            ("Can you annotate crowded scenes?",
             "Yes, with clear rules for which people are labelled, how occlusion is handled and how IDs persist."),
            ("How do you handle privacy in footage of people?",
             "Footage is accessed only by the assigned project team under the confidentiality controls agreed for "
             "the project. See our Security page for details."),
            ("Can you combine activities with pose keypoints?",
             "Yes. Many datasets pair activity segments with body or hand keypoints on selected frames."),
        ],
        "related_services": ["action-activity-annotation", "video-annotation", "image-annotation"],
        "related_pages": ["action-recognition-dataset", "video-segmentation", "robotic-task-annotation"],
    },
    {
        "slug": "robotic-task-annotation",
        "name": "Robotic Task Annotation",
        "icon": "bot",
        "visual": "timeline",
        "project_type": "Action & activity annotation",
        "title": "Robotic Task Annotation for Robot Learning Datasets",
        "meta": (
            "Robotic task annotation for robot learning datasets: task and sub-task segmentation, manipulation "
            "actions, hand-object interaction, keypoints and structured action descriptions."
        ),
        "h1": "Robotic Task Annotation",
        "eyebrow": "Data for robot learning",
        "lead": (
            "Task segmentation, manipulation actions and hand-object interactions annotated for robot learning and "
            "manipulation research."
        ),
        "intro": [
            "Robot learning datasets — human demonstrations, egocentric recordings or robot-arm footage — need to "
            "be broken into tasks and sub-tasks, with clear labels for each manipulation step.",
            "This builds directly on our action annotation work: precise action boundaries, correct hand or gripper "
            "attribution, object identity and structured descriptions such as “Right hand picks up a cup.”",
        ],
        "deliver": [
            ("Task & sub-task segmentation", "Demonstrations split into ordered manipulation steps."),
            ("Manipulation actions", "Reach, grasp, pick up, move, place, open, close, put down."),
            ("Hand / gripper attribution", "Which hand or end-effector performs each step."),
            ("Object interaction", "Which object is manipulated and where it is placed."),
            ("Keypoints", "Hand, object and robotic keypoints where required."),
            ("Step descriptions", "Structured Hand + Action + Object language per step."),
        ],
        "process": [
            "Share demonstrations, the task list and expected output.",
            "Agree step definitions and boundary rules in a pilot.",
            "Train the team on manipulation vocabulary.",
            "Review every step boundary; QA across annotators.",
            "Deliver step segments, labels and descriptions.",
        ],
        "qa": ["Step boundary accuracy", "Hand / action / object matching", "Object identity", "Vocabulary consistency", "Missing step detection"],
        "formats": ["Segment JSON", "CSV", "JSONL", "Keypoint JSON", "Custom formats"],
        "faqs": [
            ("Do you annotate robot-arm footage as well as human demonstrations?",
             "Yes. The same segmentation and interaction rules apply; guidelines specify gripper states instead of hands."),
            ("Can you label task success or failure?",
             "Yes, if your schema includes outcome labels, they can be added at task or step level."),
            ("Do you work with egocentric video?", "Yes. First-person recordings are common in manipulation datasets and our guidelines cover them."),
        ],
        "related_services": ["action-activity-annotation", "action-description", "video-annotation"],
        "related_pages": ["action-recognition-dataset", "human-activity-annotation", "video-segmentation"],
    },
]

SOLUTION_PAGE_BY_SLUG = {p["slug"]: p for p in SOLUTION_PAGES}

# ─── Industries ─────────────────────────────────────────────────────────────

INDUSTRIES = [
    {
        "slug": "retail", "name": "Retail & E-commerce", "icon": "shopping-cart", "tone": _tone("pink"),
        "summary": "Product, shelf and in-store video annotation for retail analytics and catalogue AI.",
        "items": ["Product detection", "Shelf monitoring", "Customer activity", "Theft / suspicious activity detection", "Shopping behaviour"],
        "services": ["image-annotation", "video-annotation"],
    },
    {
        "slug": "robotics", "name": "Robotics", "icon": "bot", "tone": _tone("amber"),
        "summary": "Task, action and interaction labels for robot learning and manipulation.",
        "items": ["Robotic task segmentation", "Object interaction", "Hand / object actions", "Keypoint annotation", "Manipulation tasks"],
        "services": ["action-activity-annotation", "action-description"],
    },
    {
        "slug": "autonomous-systems", "name": "Autonomous Systems", "icon": "car", "tone": _tone("cyan"),
        "summary": "Detection, tracking and scene labels for vehicles, drones and mobile robots.",
        "items": ["Object detection", "Object tracking", "Scene understanding", "Road / environment annotation"],
        "services": ["image-annotation", "video-annotation"],
    },
    {
        "slug": "healthcare", "name": "Healthcare", "icon": "stethoscope", "tone": _tone("lime"),
        "summary": "Medical image annotation following guidelines provided by your clinical experts.",
        "items": ["Bounding boxes on medical images", "Region segmentation per expert protocols", "Image classification to client-defined categories", "Consistency review against reference examples"],
        "note": "Clinical and diagnostic judgement comes from your domain experts. Our role is precise, guideline-driven annotation and QA.",
        "services": ["image-annotation"],
    },
    {
        "slug": "manufacturing", "name": "Manufacturing", "icon": "factory", "tone": _tone("violet"),
        "summary": "Visual inspection and workstation data for industrial computer vision.",
        "items": ["Defect detection", "Industrial object detection", "Worker activity", "Quality inspection"],
        "services": ["image-annotation", "action-activity-annotation"],
    },
    {
        "slug": "agriculture", "name": "Agriculture", "icon": "sprout", "tone": _tone("lime"),
        "summary": "Crop, plant and fruit annotation for agricultural monitoring.",
        "items": ["Crop / object detection", "Plant / fruit annotation", "Agricultural monitoring"],
        "services": ["image-annotation", "video-annotation"],
    },
    {
        "slug": "security", "name": "Security & Surveillance", "icon": "cctv", "tone": _tone("brand"),
        "summary": "People, activity and event annotation for security video analytics.",
        "items": ["Human detection", "Activity recognition", "Object tracking", "Event detection"],
        "services": ["video-annotation", "action-activity-annotation"],
    },
    {
        "slug": "sports", "name": "Sports", "icon": "trophy", "tone": _tone("amber"),
        "summary": "Player, pose and event annotation for sports analytics.",
        "items": ["Player tracking", "Action recognition", "Pose / keypoints", "Event annotation"],
        "services": ["video-annotation", "image-annotation"],
    },
    {
        "slug": "research", "name": "AI / Robotics Research", "icon": "atom", "tone": _tone("cyan"),
        "summary": "Carefully specified datasets for academic and industrial research teams.",
        "items": ["Action datasets", "Egocentric video", "Robotic manipulation", "Human-object interaction"],
        "services": ["action-activity-annotation", "action-description"],
    },
]

# ─── Quality, workflow, platforms, security ─────────────────────────────────

QA_STEPS = [
    {"name": "Annotation", "icon": "pen-tool", "tone": _tone("violet"), "text": "Trained annotators label data following the project guideline."},
    {"name": "Review", "icon": "eye", "tone": _tone("cyan"), "text": "Reviewers check every batch for accuracy and completeness."},
    {"name": "QA", "icon": "shield-check", "tone": _tone("lime"), "text": "An independent QA layer validates samples against the guideline."},
    {"name": "Correction", "icon": "refresh-cw", "tone": _tone("amber"), "text": "Issues are corrected and re-checked; feedback goes back to the team."},
    {"name": "Final Delivery", "icon": "package", "tone": _tone("pink"), "text": "Validated data is delivered in the agreed format."},
]

QA_CHECKS = [
    ("Annotation accuracy", "Labels match what is actually in the data.", "target"),
    ("Label consistency", "The same thing is labelled the same way across the dataset.", "repeat"),
    ("Object accuracy", "Correct class, attributes and identity for every object.", "box-select"),
    ("Action accuracy", "The right action label for every segment.", "activity"),
    ("Hand / action / object matching", "Hand, verb and object agree with the video.", "list-tree"),
    ("Boundary accuracy", "Tight boxes, clean mask edges and frame-accurate segments.", "scan"),
    ("Missing annotation detection", "Sweeps for objects, actions or fields that were skipped.", "scan-search"),
    ("Duplicate / error detection", "Duplicated labels, wrong IDs and broken tracks are caught.", "copy"),
    ("Guideline compliance", "Every decision follows the agreed guideline and edge-case log.", "book-open"),
]

CLIENT_WORKFLOW = [
    {"name": "Requirement Review", "icon": "clipboard-list", "text": "You share guidelines, examples and the expected output."},
    {"name": "Pilot / Test", "icon": "flag", "text": "Our team completes a sample task so you can review quality."},
    {"name": "Team Setup", "icon": "users", "text": "We assign trained annotators and QA members to your project."},
    {"name": "Production & Quality Control", "icon": "workflow", "text": "Annotation, review and QA run on every batch."},
    {"name": "Delivery", "icon": "package", "text": "The final validated dataset is delivered according to your specifications."},
]

ENVIRONMENTS = [
    ("Client-provided servers", "server"),
    ("Dedicated annotation servers", "server-cog"),
    ("CVAT", "box-select"),
    ("Supervisely", "layers"),
    ("Roboflow", "scan"),
    ("Custom platforms", "code"),
    ("Other client-specific environments", "settings-2"),
]

DATA_FORMATS = ["YOLO", "COCO", "Pascal VOC", "KITTI", "JSON", "CSV", "XML", "Masks", "Custom client formats"]

SECURITY_ITEMS = [
    ("Confidential project handling", "Project data is used only for your project and handled under agreed confidentiality terms.", "folder-lock"),
    ("Controlled employee access", "Only team members assigned to your project can access its data and guidelines.", "user-check"),
    ("Role-based permissions", "Annotators, reviewers, QA and managers each see only what their role requires.", "key"),
    ("Secure login", "Individual accounts and secure sign-in — no shared credentials.", "lock-keyhole"),
    ("Project-specific access", "Access is granted per project and removed when someone leaves it.", "id-card"),
    ("NDA support", "Non-disclosure agreements with your organisation and team members where required.", "file-check"),
    ("No unauthorised dataset sharing", "Data is never shared, reused or published outside your project.", "eye-off"),
    ("Secure internal training environment", "Training, tutorials and feedback run on our own access-controlled portal.", "graduation-cap"),
]

TEAM_ROLES = [
    {"name": "Annotators", "icon": "pen-tool", "text": "Trained on your guideline and tested before production."},
    {"name": "Team leads", "icon": "user-cog", "text": "Coordinate the team and resolve guideline questions."},
    {"name": "Reviewers", "icon": "eye", "text": "Check every batch for accuracy and completeness."},
    {"name": "QA members", "icon": "shield-check", "text": "Independent quality checks and final validation."},
]

TRAINING_SYSTEM = [
    ("Project tutorials", "Video and written tutorials for every project guideline.", "circle-play"),
    ("Tests before production", "Annotators pass project-specific tests before working on live data.", "clipboard-check"),
    ("Daily feedback", "Reviewers and QA share daily feedback on real examples.", "message-square"),
    ("Retraining", "Recurring issues trigger refresher tutorials and re-tests.", "rotate-ccw"),
]

CAPABILITY_PILLARS = [
    ("users", "Skilled annotation workforce", "Annotators trained in image, video, action and text annotation, selected for attention to detail and consistency."),
    ("globe", "Remote workforce", "A remote team model that lets us staff projects flexibly while keeping the same training, tools and QA standards."),
    ("briefcase", "Dedicated project teams", "Each project gets its own team, so annotators build up knowledge of your guideline and edge cases."),
    ("user-cog", "Team leads, reviewers & QA", "Clear roles: team leads coordinate, reviewers check every batch and QA members validate independently."),
    ("graduation-cap", "Structured training system", "Tutorials, tests and daily feedback on our internal training portal — before and during production."),
    ("layers", "Large-volume project capability", "Batch-based production, progress tracking and QA sampling designed for large datasets."),
]

SCALE_STEPS = [
    ("Pilot team", "A small, experienced group completes the pilot and documents edge cases with you."),
    ("Core team", "A core team is trained on the agreed guideline and must pass project tests."),
    ("Capacity in waves", "Additional annotators join in waves, using the same tutorials, tests and feedback."),
    ("QA scales with volume", "Reviewers and QA members are added alongside annotators to keep checks consistent."),
]

FEEDBACK_LOOP = [
    {"name": "QA finds an issue", "x": 50, "y": 9},
    {"name": "Daily feedback with examples", "x": 83, "y": 50},
    {"name": "Refresher tutorial or re-test", "x": 50, "y": 91},
    {"name": "Re-checked in the next batch", "x": 17, "y": 50},
]

QUALITY_PRINCIPLES = [
    ("flag", "Pilot calibration", "Quality expectations are calibrated on a pilot batch before production starts."),
    ("list-checks", "Agreed acceptance criteria", "Sampling and acceptance criteria are agreed with you, not assumed."),
    ("book-open", "A living guideline", "Edge cases are logged and added to the guideline so decisions stay consistent."),
]

ACCESS_MATRIX = [
    ("Annotator", True, True, False, False),
    ("Reviewer", True, True, True, False),
    ("QA member", True, True, True, False),
    ("Project manager", True, True, True, True),
]

ABOUT_FOCUS = [
    ("sparkles", "Annotation specialists", "AI data annotation is our core business, not a side service."),
    ("users", "Skilled workforce", "Annotators selected for attention to detail and trained per project."),
    ("globe", "Remote team", "A remote team model with shared tools, training and QA standards."),
    ("layers", "Large project capability", "Batch-based production and team structures built for volume."),
    ("shield-check", "Quality-focused workflow", "Annotation, review, QA and correction on every batch."),
    ("clapperboard", "Video, image & text", "Experience across visual and language annotation, with a video and action focus."),
    ("handshake", "Long-term collaboration", "Teams that stay with your project and learn your edge cases."),
    ("graduation-cap", "Structured training & QA", "Tutorials, tests and daily feedback on our internal portal."),
]

ABOUT_PRINCIPLES = [
    ("target", "Accuracy over speed", "We agree quality targets first and plan throughput around them."),
    ("repeat", "Consistency", "Written rules, edge-case logs and review keep labels uniform."),
    ("eye", "Transparency", "Pilot first, honest scoping and clear reporting on progress and issues."),
    ("lock-keyhole", "Confidentiality", "Project-specific access and no unauthorised data sharing."),
]

QUOTE_NEXT_STEPS = [
    ("inbox", "We review your request", "Our team reads your requirements and any samples you shared."),
    ("message-square", "Clarifying questions", "We confirm classes, edge cases, volume, format and timeline with you."),
    ("flag", "Pilot / test task", "We complete a sample task so you can evaluate quality on your data."),
    ("file-check", "Proposal & team setup", "You receive a proposal; once agreed, we set up your dedicated team."),
]

QUOTE_HELPFUL = [
    "Annotation guideline or label list",
    "A few sample images, clips or documents",
    "Expected output format (e.g. COCO, YOLO, JSON)",
    "Estimated volume and timeline",
    "Quality or acceptance criteria",
]

# ─── FAQs ───────────────────────────────────────────────────────────────────

HOME_FAQS = [
    ("What types of data do you annotate?",
     "Images, video, text and documents — including multimodal projects such as video with structured action "
     "descriptions. See our services for the full list of annotation types."),
    ("Do you build or train AI models?", "No. " + DATASET_STATEMENT),
    ("Can you work on our annotation platform?",
     TOOLS_STATEMENT + " Teams regularly work in client-provided environments as well as tools such as CVAT, "
     "Supervisely or Roboflow, depending on the project."),
    ("How do you make sure the annotations are accurate?",
     "Every project runs through annotation, review, QA and correction before delivery. Annotators are trained and "
     "tested on your guideline, and daily feedback keeps recurring issues from repeating."),
    ("Can you handle large or long-running projects?", SCALE_STATEMENT),
    ("How do we get started?",
     "Send a quote request with your use case, data type and estimated volume. We review your requirements and "
     "usually suggest a short pilot so you can evaluate quality before production."),
    ("How do you keep our data confidential?",
     "Access is project-specific and role-based, team members use individual secure logins, NDAs are supported "
     "where required and data is never shared outside your project."),
    ("Which output formats do you deliver?",
     "Common formats include YOLO, COCO, Pascal VOC, KITTI, JSON, CSV, XML and masks. " + FORMATS_NOTE),
]

QUALITY_FAQS = [
    ("Who performs QA — the same people who annotate?",
     "No. Review and QA are separate roles. Reviewers check every batch, and QA members validate samples "
     "independently before delivery."),
    ("What happens when QA finds an error?",
     "The item goes back for correction and is re-checked. If the issue is recurring, it becomes part of the next "
     "day's feedback and, where needed, a refresher tutorial or re-test."),
    ("Can we define our own acceptance criteria?",
     "Yes. Acceptance criteria and sampling are agreed with you during the requirement review and pilot."),
]

CAREERS_FAQS = [
    ("Do I need previous annotation experience?",
     "It helps, but it is not always required. Attention to detail, consistency and the ability to follow written "
     "guidelines matter most — project-specific training is provided."),
    ("Is the work remote?",
     "Many roles are remote. Work type depends on the project — choose your preference in the form."),
    ("What happens after I apply?",
     "Our team reviews your information and contacts you if your profile matches an available project. Selected "
     "applicants receive a portal account, onboarding, tutorials and a short test."),
    ("I was asked to create a portal account. Where do I do that?",
     "If our team has asked you to create an account, use the team sign-up page linked on this page."),
]

WHY_JOIN = [
    ("graduation-cap", "Structured training", "Project tutorials and tests prepare you before you work on live data."),
    ("message-square", "Daily feedback", "Reviewers and QA share feedback on real examples so you improve quickly."),
    ("laptop", "Remote options", "Many projects can be done remotely; choose the work type that suits you."),
    ("trending-up", "A clear growth path", "Consistent annotators can grow into reviewer and QA roles."),
]

TRAINING_STEPS = [
    ("send", "Apply", "Submit the form with your CV and experience."),
    ("user-search", "Profile review", "We contact you if your profile matches an available project."),
    ("user-check", "Portal account", "Selected applicants get access to our training portal."),
    ("circle-play", "Tutorials & test", "Learn the project guideline and pass a short test."),
    ("pen-tool", "Project work", "Start annotating, with daily feedback from review and QA."),
]

# ─── Form choices ───────────────────────────────────────────────────────────

PROJECT_TYPES = [s["project_type"] for s in SERVICES] + ["Other"]

PLATFORM_CHOICES = [
    "Not sure yet",
    "CVAT",
    "Supervisely",
    "Roboflow",
    "Our own platform (client-provided)",
    f"{BRAND_NAME}-provided annotation server",
    "Other / custom",
]

TIMELINE_CHOICES = [
    "As soon as possible",
    "Within 2 weeks",
    "Within 1 month",
    "1 – 3 months",
    "Ongoing / recurring",
    "Flexible / not sure",
]

EXPERIENCE_CHOICES = [
    "No professional experience yet",
    "Less than 6 months",
    "6 – 12 months",
    "1 – 2 years",
    "More than 2 years",
]

WORK_TYPE_CHOICES = [
    "Remote — full-time",
    "Remote — part-time",
    "On-site",
    "Contract / project-based",
    "Flexible",
]

AVAILABILITY_CHOICES = [
    "Immediately",
    "Within 1 week",
    "Within 2 weeks",
    "Within 1 month",
    "Flexible / to discuss",
]

SKILL_CHOICES = [
    "Bounding boxes", "Polygons / segmentation", "Keypoints", "Video annotation", "Object tracking",
    "Action / activity labeling", "Action descriptions (writing)", "Text / NLP annotation", "OCR / transcription",
    "Quality review / QA", "CVAT", "Supervisely", "Roboflow", "English writing",
]

CAREER_ROLES = [
    {
        "name": "Annotator", "icon": "pen-tool", "tone": _tone("violet"),
        "text": "Label images, video, actions or text following project guidelines.",
        "points": ["Project-specific training and tests", "Daily feedback on your work", "Remote options on many projects"],
    },
    {
        "name": "Reviewer", "icon": "eye", "tone": _tone("cyan"),
        "text": "Check annotators' batches for accuracy and completeness, and send work back for correction.",
        "points": ["For experienced annotators", "Strong guideline knowledge", "Clear, constructive feedback"],
    },
    {
        "name": "QA member", "icon": "shield-check", "tone": _tone("lime"),
        "text": "Validate samples independently, track recurring issues and help keep delivery quality consistent.",
        "points": ["Independent quality checks", "Edge-case and guideline expertise", "Works with team leads"],
    },
]


def footer_solution_links():
    return [(p["slug"], p["name"]) for p in SOLUTION_PAGES]
