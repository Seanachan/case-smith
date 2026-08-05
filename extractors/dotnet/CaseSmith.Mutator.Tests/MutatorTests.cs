using CaseSmith.Mutator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.VisualBasic;
using Xunit;

namespace CaseSmith.Mutator.Tests;

/// <summary>
/// Structural assertions against mutant generation for Fixtures/RiskEngine.vb
/// -- exact before/after text, exact line numbers, and disk-level guarantees
/// (single-line diff per mutant, determinism, re-parse cleanliness).
/// </summary>
public class MutatorTests
{
    private static readonly string FixturesDir = Path.Combine(AppContext.BaseDirectory, "Fixtures");

    private static MutantRecord Find(List<MutantRecord> mutants, string op, int line) =>
        mutants.Single(m => m.Operator == op && m.Line == line);

    [Fact]
    public void CompareInvert_FlipsGreaterThanOrEqualToLessThan()
    {
        var result = MutantGenerator.Generate(FixturesDir);
        var m = Find(result.Mutants, "compare_invert", 12);

        Assert.Equal("score >= threshold", m.Original);
        Assert.Equal("score < threshold", m.Mutated);
        Assert.Equal("RiskEngine.vb", m.File);
        Assert.Equal("RiskEngine.vb_12_compare_invert_1", m.Id);
    }

    [Fact]
    public void ArithmeticSwap_CoversAllFourOperatorPairs()
    {
        var result = MutantGenerator.Generate(FixturesDir);

        Assert.Equal(("a + b", "a - b"), Pair(Find(result.Mutants, "arithmetic_swap", 19)));
        Assert.Equal(("a - b", "a + b"), Pair(Find(result.Mutants, "arithmetic_swap", 20)));
        Assert.Equal(("a * b", "a \\ b"), Pair(Find(result.Mutants, "arithmetic_swap", 21)));
        Assert.Equal(("a \\ b", "a * b"), Pair(Find(result.Mutants, "arithmetic_swap", 22)));

        static (string, string) Pair(MutantRecord m) => (m.Original, m.Mutated);
    }

    [Fact]
    public void BooleanFlip_TogglesTrueAndFalseLiterals()
    {
        var result = MutantGenerator.Generate(FixturesDir);

        var flips = result.Mutants.Where(m => m.Operator == "boolean_flip").ToList();
        Assert.Equal(3, flips.Count);
        Assert.Equal(("True", "False"), (Find(result.Mutants, "boolean_flip", 13).Original, Find(result.Mutants, "boolean_flip", 13).Mutated));
        Assert.Equal(("False", "True"), (Find(result.Mutants, "boolean_flip", 15).Original, Find(result.Mutants, "boolean_flip", 15).Mutated));
        Assert.Equal(("True", "False"), (Find(result.Mutants, "boolean_flip", 27).Original, Find(result.Mutants, "boolean_flip", 27).Mutated));
    }

    [Fact]
    public void SqlStringLiteral_ContributesNoMutants()
    {
        // Line 10 holds the SQL string literal with "=" and "+" inside its
        // text. None of that text is a syntax node, so it must never surface
        // as a mutant -- exactly 8 total across the whole fixture confirms
        // the literal's internals were skipped, not just under-matched.
        var result = MutantGenerator.Generate(FixturesDir);

        Assert.DoesNotContain(result.Mutants, m => m.Line == 10);
        Assert.Equal(8, result.Mutants.Count);
        Assert.Empty(result.Skipped);
    }

    [Fact]
    public void ManifestIsSortedById()
    {
        var result = MutantGenerator.Generate(FixturesDir);
        var ids = result.Mutants.Select(m => m.Id).ToList();

        Assert.Equal(ids.OrderBy(x => x, StringComparer.Ordinal).ToList(), ids);
    }

    [Fact]
    public void EveryMutantTree_DiffersFromOriginalByExactlyOneLine()
    {
        var result = MutantGenerator.Generate(FixturesDir);
        var outDir = Path.Combine(Path.GetTempPath(), "casesmith-mutator-test-" + Guid.NewGuid());
        var mutantsDir = Path.Combine(outDir, "mutants");
        Directory.CreateDirectory(mutantsDir);

        try
        {
            var originalLines = File.ReadAllLines(Path.Combine(FixturesDir, "RiskEngine.vb"));

            foreach (var mutant in result.Mutants)
            {
                var (relativeFile, mutatedText) = result.MutatedFileById[mutant.Id];
                MutantGenerator.WriteMutantTree(FixturesDir, mutantsDir, mutant.Id, relativeFile, mutatedText);

                var mutatedFilePath = Path.Combine(mutantsDir, mutant.Id, relativeFile);
                var mutatedLines = File.ReadAllLines(mutatedFilePath);

                Assert.Equal(originalLines.Length, mutatedLines.Length);
                var diffCount = originalLines
                    .Zip(mutatedLines, (a, b) => a == b ? 0 : 1)
                    .Sum();
                Assert.Equal(1, diffCount);
            }
        }
        finally
        {
            Directory.Delete(outDir, recursive: true);
        }
    }

    [Fact]
    public void Generate_IsDeterministic_AcrossRepeatedRuns()
    {
        var first = MutantGenerator.Generate(FixturesDir);
        var second = MutantGenerator.Generate(FixturesDir);

        Assert.Equal(first.Mutants.Count, second.Mutants.Count);
        for (var i = 0; i < first.Mutants.Count; i++)
        {
            Assert.Equal(first.Mutants[i].Id, second.Mutants[i].Id);
            Assert.Equal(first.Mutants[i].Original, second.Mutants[i].Original);
            Assert.Equal(first.Mutants[i].Mutated, second.Mutants[i].Mutated);
        }
        Assert.Equal(first.Skipped.Count, second.Skipped.Count);
    }

    [Fact]
    public void AllMutatedFiles_ReparseWithoutSyntaxErrors()
    {
        var result = MutantGenerator.Generate(FixturesDir);

        Assert.NotEmpty(result.Mutants);
        foreach (var (_, mutatedText) in result.MutatedFileById.Values)
        {
            var tree = VisualBasicSyntaxTree.ParseText(mutatedText);
            Assert.DoesNotContain(tree.GetDiagnostics(), d => d.Severity == DiagnosticSeverity.Error);
        }
    }
}
