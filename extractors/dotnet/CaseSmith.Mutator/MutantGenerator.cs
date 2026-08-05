using System.Text;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.VisualBasic;

namespace CaseSmith.Mutator;

/// <summary>
/// Orchestrates mutant discovery for one input directory: parse every .vb
/// file, ask <see cref="MutationOperators"/> for candidates, re-parse each
/// mutated file to check it's still syntactically valid, and produce a
/// deterministic manifest. File I/O for materializing mutant trees is kept
/// separate (<see cref="WriteMutantTree"/>) so <see cref="Generate"/> stays
/// easy to unit test without touching disk beyond reading the input.
/// </summary>
internal static class MutantGenerator
{
    public sealed class GenerationResult
    {
        public required List<MutantRecord> Mutants { get; init; }
        public required List<SkippedMutantRecord> Skipped { get; init; }

        /// <summary>id -> (file-relative-to-input, full mutated file text).</summary>
        public required Dictionary<string, (string RelativeFile, string MutatedText)> MutatedFileById { get; init; }
    }

    public static GenerationResult Generate(string inputDir)
    {
        var files = Directory
            .EnumerateFiles(inputDir, "*.vb", SearchOption.AllDirectories)
            .OrderBy(f => f, StringComparer.Ordinal)
            .ToList();

        var mutants = new List<MutantRecord>();
        var skipped = new List<SkippedMutantRecord>();
        var mutatedById = new Dictionary<string, (string RelativeFile, string MutatedText)>(StringComparer.Ordinal);

        foreach (var file in files)
        {
            var relative = Path.GetRelativePath(inputDir, file).Replace(Path.DirectorySeparatorChar, '/');
            var text = File.ReadAllText(file);
            var tree = VisualBasicSyntaxTree.ParseText(text, path: file);
            var root = tree.GetRoot();

            // Sequence number resets per (line, operator) -- lets two mutable
            // sites on the same line and operator get distinct, stable ids.
            var seqByKey = new Dictionary<(int Line, string Op), int>();

            foreach (var candidate in MutationOperators.FindCandidates(root))
            {
                var key = (candidate.Line, candidate.Operator);
                seqByKey.TryGetValue(key, out var seq);
                seq++;
                seqByKey[key] = seq;

                var id = BuildId(relative, candidate.Line, candidate.Operator, seq);
                var mutatedRoot = root.ReplaceNode(candidate.TargetNode, candidate.ReplacementNode);
                var mutatedText = mutatedRoot.ToFullString();

                var reparsed = VisualBasicSyntaxTree.ParseText(mutatedText, path: file);
                var hasSyntaxError = reparsed.GetDiagnostics().Any(d => d.Severity == DiagnosticSeverity.Error);

                if (hasSyntaxError)
                {
                    skipped.Add(new SkippedMutantRecord
                    {
                        Id = id,
                        File = relative,
                        Line = candidate.Line,
                        Operator = candidate.Operator,
                        Original = candidate.OriginalText,
                        Mutated = candidate.MutatedText,
                        Reason = "syntax_error_after_mutation",
                    });
                    continue;
                }

                mutants.Add(new MutantRecord
                {
                    Id = id,
                    File = relative,
                    Line = candidate.Line,
                    Operator = candidate.Operator,
                    Original = candidate.OriginalText,
                    Mutated = candidate.MutatedText,
                });
                mutatedById[id] = (relative, mutatedText);
            }
        }

        mutants = mutants.OrderBy(m => m.Id, StringComparer.Ordinal).ToList();
        skipped = skipped.OrderBy(s => s.Id, StringComparer.Ordinal).ToList();

        return new GenerationResult { Mutants = mutants, Skipped = skipped, MutatedFileById = mutatedById };
    }

    /// <summary>
    /// Copies the whole input tree into `&lt;mutantsDir&gt;/&lt;mutantId&gt;/`,
    /// substituting <paramref name="mutatedText"/> for the one file that
    /// changed. Every other file is byte-for-byte the original.
    /// </summary>
    public static void WriteMutantTree(
        string inputDir, string mutantsDir, string mutantId, string relativeMutatedFile, string mutatedText)
    {
        var destRoot = Path.Combine(mutantsDir, mutantId);
        Directory.CreateDirectory(destRoot);

        foreach (var srcFile in Directory.EnumerateFiles(inputDir, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(inputDir, srcFile);
            var destFile = Path.Combine(destRoot, relative);
            var destDir = Path.GetDirectoryName(destFile);
            if (!string.IsNullOrEmpty(destDir)) Directory.CreateDirectory(destDir);

            var relativeNormalized = relative.Replace(Path.DirectorySeparatorChar, '/');
            if (relativeNormalized == relativeMutatedFile)
                File.WriteAllText(destFile, mutatedText, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            else
                File.Copy(srcFile, destFile, overwrite: true);
        }
    }

    private static string BuildId(string relativeFile, int line, string op, int seq)
    {
        var safeFile = relativeFile.Replace('/', '_').Replace('\\', '_');
        return $"{safeFile}_{line}_{op}_{seq}";
    }
}
