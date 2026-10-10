"""Typed tool contracts and the generic registry exposed to the model."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFilesArgs(Args):
    dir: str = Field(default=".", description="Directory relative to the configured file root.")


class ReadFileArgs(Args):
    path: str = Field(description="File path relative to the configured file root.")
    offset: int = Field(default=0, ge=0, description="Character offset for the next chunk.")


class SearchFilesArgs(Args):
    query: str = Field(description="Text to search for, case-insensitively.")
    dir: str = Field(default=".", description="Optional directory relative to the file root.")


class BrowserOpenArgs(Args):
    url: str = Field(description="Relative path or URL on the configured environment origin.")


class ElementArgs(Args):
    element_id: str = Field(description="Element id from the latest browser observation.")


class TypeArgs(ElementArgs):
    text: str = Field(description="Text to enter.")
    clear: bool = Field(default=True, description="Replace existing text when true.")


class SelectArgs(ElementArgs):
    option: str = Field(description="Visible option label to select.")


class ScreenshotArgs(Args):
    label: str = Field(description="Short evidence filename label.")


class CalculateArgs(Args):
    expression: str = Field(description="Arithmetic expression using numbers and basic operators.")


class NoteArgs(Args):
    key: str = Field(description="Short memory key.")
    value: str = Field(description="Fact to remember for this run.")


class AskUserArgs(Args):
    question: str = Field(description="Clear question for the human.")
    options: list[str] = Field(default_factory=list, description="Optional choices.")


class Claim(Args):
    claim: str
    how_to_check: str
    evidence_ref: str = ""


class FinishArgs(Args):
    status: Literal["success", "partial", "blocked", "failed"]
    summary: str
    claims: list[Claim] = Field(default_factory=list)


class VerificationItem(Args):
    claim: str
    status: Literal["confirmed", "contradicted", "unverifiable"]
    evidence: str


class VerificationReportArgs(Args):
    results: list[VerificationItem]


class ToolDefinition:
    def __init__(self, name: str, description: str, model: type[BaseModel], risk: str = "none"):
        self.name = name
        self.description = description
        self.model = model
        self.risk = risk

    def declaration(self) -> dict[str, Any]:
        schema = self.model.model_json_schema()
        definitions = schema.pop("$defs", {})

        def clean(value):
            if isinstance(value, list):
                return [clean(item) for item in value]
            if not isinstance(value, dict):
                return value
            if "$ref" in value:
                name = value["$ref"].rsplit("/", 1)[-1]
                return clean(definitions[name])
            allowed = {"type", "description", "properties", "required", "items", "enum", "minimum", "maximum", "anyOf"}
            result = {}
            for key, item in value.items():
                if key not in allowed:
                    continue
                if key == "properties":
                    result[key] = {name: clean(field_schema) for name, field_schema in item.items()}
                else:
                    result[key] = clean(item)
            return result

        schema = clean(schema)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema,
        }


TOOL_DEFINITIONS = [
    ToolDefinition("list_files", "List file names under the read-only file root. Example: dir='inbox'.", ListFilesArgs),
    ToolDefinition("read_file", "Read a UTF-8 text file under the file root. Large files return a next offset.", ReadFileArgs),
    ToolDefinition("search_files", "Find matching lines under the file root and return file and line numbers.", SearchFilesArgs),
    ToolDefinition("browser_open", "Open a page within the configured environment origin and return visible text and controls.", BrowserOpenArgs),
    ToolDefinition("browser_observe", "Re-read the current page, visible text, controls, and any form errors.", Args),
    ToolDefinition("browser_click", "Click a control by element_id from the latest observation. Risk metadata is enforced in code.", ElementArgs, "dynamic"),
    ToolDefinition("browser_type", "Enter text in an input or text area by element_id. Reversible page interaction.", TypeArgs, "reversible"),
    ToolDefinition("browser_select", "Select a visible option by label from a select control. Reversible page interaction.", SelectArgs, "reversible"),
    ToolDefinition("browser_screenshot", "Save a screenshot as human-review evidence; screenshot bytes are not sent to the model.", ScreenshotArgs),
    ToolDefinition("calculate", "Evaluate safe basic arithmetic without executing Python code.", CalculateArgs),
    ToolDefinition("note", "Save a useful fact in this run's working memory.", NoteArgs),
    ToolDefinition("ask_user", "Ask the human when the task is ambiguous or an approval decision is required.", AskUserArgs),
    ToolDefinition("finish", "Submit a final status, concise summary, and verifiable claims.", FinishArgs),
]

READ_ONLY_NAMES = {"list_files", "read_file", "search_files", "browser_open", "browser_observe", "browser_screenshot", "calculate"}


def definitions(read_only: bool = False) -> dict[str, ToolDefinition]:
    selected = [d for d in TOOL_DEFINITIONS if not read_only or d.name in READ_ONLY_NAMES]
    if read_only:
        selected.append(ToolDefinition(
            "report_verification", "Return a status and evidence assessment for each requested claim.",
            VerificationReportArgs,
        ))
    return {definition.name: definition for definition in selected}

