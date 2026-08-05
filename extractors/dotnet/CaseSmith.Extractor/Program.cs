using System.Text;
using System.Text.Json;
using CaseSmith.Extractor;
using Microsoft.CodeAnalysis.VisualBasic;

string? inputDir = null;
string? outputFile = null;

for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--input" when i + 1 < args.Length:
            inputDir = args[++i];
            break;
        case "--output" when i + 1 < args.Length:
            outputFile = args[++i];
            break;
        default:
            Console.Error.WriteLine($"Unknown or incomplete argument: {args[i]}");
            return 1;
    }
}

if (inputDir is null || outputFile is null)
{
    Console.Error.WriteLine("Usage: CaseSmith.Extractor --input <dir> --output <file>");
    return 1;
}

inputDir = Path.GetFullPath(inputDir);
if (!Directory.Exists(inputDir))
{
    Console.Error.WriteLine($"Input directory not found: {inputDir}");
    return 1;
}

var files = Directory
    .EnumerateFiles(inputDir, "*.vb", SearchOption.AllDirectories)
    .OrderBy(f => f, StringComparer.Ordinal)
    .ToList();

var methods = new List<MethodCard>();
foreach (var file in files)
{
    var text = File.ReadAllText(file);
    var tree = VisualBasicSyntaxTree.ParseText(text, path: file);
    var relative = Path.GetRelativePath(inputDir, file).Replace(Path.DirectorySeparatorChar, '/');
    methods.AddRange(MethodExtractor.ExtractMethods(tree, relative));
}

var card = new SpecCard
{
    Source = new SourceInfo(),
    Methods = methods.OrderBy(m => m.Id, StringComparer.Ordinal).ToList(),
};

var jsonOptions = new JsonSerializerOptions
{
    WriteIndented = true,
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
};
var json = JsonSerializer.Serialize(card, jsonOptions);

var outputFullPath = Path.GetFullPath(outputFile);
var outDir = Path.GetDirectoryName(outputFullPath);
if (!string.IsNullOrEmpty(outDir)) Directory.CreateDirectory(outDir);
File.WriteAllText(outputFullPath, json, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

Console.WriteLine($"Wrote {methods.Count} method(s) from {files.Count} file(s) to {outputFullPath}");
return 0;
