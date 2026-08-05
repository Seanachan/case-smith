using System.Text.Json.Serialization;

namespace CaseSmith.Extractor;

/// <summary>
/// Top-level spec card. Shape is a contract shared with hand-written E2E spec
/// cards -- see docs/CONTRACTS.md ("spec card(spec.json)契約 v1"). Field names
/// and nesting must match exactly.
/// </summary>
public sealed class SpecCard
{
    [JsonPropertyName("source")]
    public SourceInfo Source { get; set; } = new();

    [JsonPropertyName("methods")]
    public List<MethodCard> Methods { get; set; } = new();
}

public sealed class SourceInfo
{
    [JsonPropertyName("language")]
    public string Language { get; set; } = "vb.net";

    [JsonPropertyName("extractor")]
    public string Extractor { get; set; } = "casesmith-dotnet";

    [JsonPropertyName("version")]
    public int Version { get; set; } = 1;
}

public sealed class MethodCard
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("file")]
    public string File { get; set; } = "";

    [JsonPropertyName("line")]
    public int Line { get; set; }

    /// <summary>
    /// One-line business summary. Always emitted, always empty from the
    /// extractor -- filled in by a dev-time strong model, not this tool.
    /// </summary>
    [JsonPropertyName("summary")]
    public string Summary { get; set; } = "";

    [JsonPropertyName("signature")]
    public Signature Signature { get; set; } = new();

    [JsonPropertyName("branch_count")]
    public int BranchCount { get; set; }

    [JsonPropertyName("tables")]
    public List<TableRef> Tables { get; set; } = new();

    [JsonPropertyName("condition_columns")]
    public List<string> ConditionColumns { get; set; } = new();

    [JsonPropertyName("unqualified_condition_columns")]
    public List<string> UnqualifiedConditionColumns { get; set; } = new();

    [JsonPropertyName("endpoints")]
    public List<Endpoint> Endpoints { get; set; } = new();

    [JsonPropertyName("dynamic_sql")]
    public bool DynamicSql { get; set; }
}

public sealed class Signature
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("params")]
    public List<Param> Params { get; set; } = new();

    [JsonPropertyName("returns")]
    public string Returns { get; set; } = "";
}

public sealed class Param
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "";
}

public sealed class TableRef
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("operations")]
    public List<string> Operations { get; set; } = new();
}

public sealed class Endpoint
{
    [JsonPropertyName("http_method")]
    public string HttpMethod { get; set; } = "";

    [JsonPropertyName("url")]
    public string Url { get; set; } = "";
}
