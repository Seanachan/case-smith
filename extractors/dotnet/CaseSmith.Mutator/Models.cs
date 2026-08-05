using System.Text.Json.Serialization;

namespace CaseSmith.Mutator;

/// <summary>
/// Top-level manifest shape -- pinned in docs handoff, see the mutation
/// injector spec card. Field names and nesting must match exactly.
/// </summary>
public sealed class MutantManifest
{
    [JsonPropertyName("source")]
    public MutantSourceInfo Source { get; set; } = new();

    [JsonPropertyName("mutants")]
    public List<MutantRecord> Mutants { get; set; } = new();

    [JsonPropertyName("skipped")]
    public List<SkippedMutantRecord> Skipped { get; set; } = new();
}

public sealed class MutantSourceInfo
{
    [JsonPropertyName("language")]
    public string Language { get; set; } = "vb.net";

    [JsonPropertyName("tool")]
    public string Tool { get; set; } = "casesmith-mutator";

    [JsonPropertyName("version")]
    public int Version { get; set; } = 1;
}

public sealed class MutantRecord
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("file")]
    public string File { get; set; } = "";

    [JsonPropertyName("line")]
    public int Line { get; set; }

    [JsonPropertyName("operator")]
    public string Operator { get; set; } = "";

    [JsonPropertyName("original")]
    public string Original { get; set; } = "";

    [JsonPropertyName("mutated")]
    public string Mutated { get; set; } = "";
}

/// <summary>
/// A mutant that was generated but discarded because the mutated file failed
/// to re-parse cleanly. Recorded, not silently dropped.
/// </summary>
public sealed class SkippedMutantRecord
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("file")]
    public string File { get; set; } = "";

    [JsonPropertyName("line")]
    public int Line { get; set; }

    [JsonPropertyName("operator")]
    public string Operator { get; set; } = "";

    [JsonPropertyName("original")]
    public string Original { get; set; } = "";

    [JsonPropertyName("mutated")]
    public string Mutated { get; set; } = "";

    [JsonPropertyName("reason")]
    public string Reason { get; set; } = "";
}
