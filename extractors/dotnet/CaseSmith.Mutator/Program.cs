using System.Text;
using System.Text.Json;
using CaseSmith.Mutator;

string? inputDir = null;
string? outputDir = null;

for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--input" when i + 1 < args.Length:
            inputDir = args[++i];
            break;
        case "--output" when i + 1 < args.Length:
            outputDir = args[++i];
            break;
        default:
            Console.Error.WriteLine($"Unknown or incomplete argument: {args[i]}");
            return 1;
    }
}

if (inputDir is null || outputDir is null)
{
    Console.Error.WriteLine("Usage: CaseSmith.Mutator --input <dir> --output <dir>");
    return 1;
}

inputDir = Path.GetFullPath(inputDir);
if (!Directory.Exists(inputDir))
{
    Console.Error.WriteLine($"Input directory not found: {inputDir}");
    return 1;
}

outputDir = Path.GetFullPath(outputDir);
var mutantsDir = Path.Combine(outputDir, "mutants");
Directory.CreateDirectory(mutantsDir);

var result = MutantGenerator.Generate(inputDir);

foreach (var mutant in result.Mutants)
{
    var (relativeFile, mutatedText) = result.MutatedFileById[mutant.Id];
    MutantGenerator.WriteMutantTree(inputDir, mutantsDir, mutant.Id, relativeFile, mutatedText);
}

var manifest = new MutantManifest
{
    Source = new MutantSourceInfo(),
    Mutants = result.Mutants,
    Skipped = result.Skipped,
};

var jsonOptions = new JsonSerializerOptions
{
    WriteIndented = true,
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
};
var json = JsonSerializer.Serialize(manifest, jsonOptions);

var manifestPath = Path.Combine(outputDir, "manifest.json");
File.WriteAllText(manifestPath, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

Console.WriteLine($"Wrote {result.Mutants.Count} mutant(s) ({result.Skipped.Count} skipped) to {outputDir}");
return 0;
