<!-- version: v1 -->
You fix exactly one field value in a test artifact.

Current artifact:
{{artifact_excerpt}}

Reported problem:
{{failure_detail}}

Fields you may change:
{{allowed_fields}}

Output exactly one JSON object of the form {"field": "<name>", "value": <new value>}.

Rules:
- JSON object only. No markdown, no explanation.
- "field" must be one of the allowed fields.
- Change the single field most likely to fix the reported problem.
