using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.VisualBasic;
using Microsoft.CodeAnalysis.VisualBasic.Syntax;

namespace CaseSmith.Extractor;

/// <summary>
/// Walks one parsed .vb file and produces one <see cref="MethodCard"/> per
/// Sub/Function that has a body (Module or Class member). Syntax-level only --
/// no MSBuildWorkspace, no semantic model (see docs/CONTRACTS.md §"spec card").
/// </summary>
internal static class MethodExtractor
{
    public static IEnumerable<MethodCard> ExtractMethods(SyntaxTree tree, string relativeFilePath)
    {
        var root = tree.GetRoot();
        foreach (var methodBlock in root.DescendantNodes().OfType<MethodBlockSyntax>())
        {
            var typeName = GetContainingTypeName(methodBlock);
            if (typeName is null) continue; // defensive: VB methods always live in a Module/Class/Structure

            yield return BuildCard(methodBlock, typeName, relativeFilePath);
        }
    }

    private static MethodCard BuildCard(MethodBlockSyntax methodBlock, string typeName, string relativeFilePath)
    {
        var stmt = methodBlock.SubOrFunctionStatement;
        var nsParts = GetContainingNamespaceParts(methodBlock);
        var idPrefix = nsParts.Count > 0 ? string.Join(".", nsParts) + "." + typeName : typeName;
        var id = $"{idPrefix}.{stmt.Identifier.Text}";

        var line = stmt.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
        var isFunction = stmt.SubOrFunctionKeyword.IsKind(SyntaxKind.FunctionKeyword);
        var returns = isFunction ? NonEmptyOrObject(stmt.AsClause?.Type?.ToString()) : "";

        var sql = SqlAnalyzer.Analyze(methodBlock);
        var endpoints = EndpointAnalyzer.Analyze(methodBlock);

        return new MethodCard
        {
            Id = id,
            File = relativeFilePath,
            Line = line,
            Summary = "",
            Signature = new Signature
            {
                Name = stmt.Identifier.Text,
                Params = ExtractParams(stmt.ParameterList),
                Returns = returns,
            },
            BranchCount = CountBranches(methodBlock),
            Tables = sql.Tables
                .Select(kv => new TableRef { Name = kv.Key, Operations = kv.Value.ToList() })
                .OrderBy(t => t.Name, StringComparer.Ordinal)
                .ToList(),
            ConditionColumns = sql.ConditionColumns.ToList(),
            UnqualifiedConditionColumns = sql.UnqualifiedConditionColumns.ToList(),
            Endpoints = endpoints
                .OrderBy(e => e.Url, StringComparer.Ordinal)
                .ThenBy(e => e.HttpMethod, StringComparer.Ordinal)
                .ToList(),
            DynamicSql = sql.DynamicSql,
        };
    }

    private static string NonEmptyOrObject(string? typeText)
    {
        var trimmed = typeText?.Trim();
        return string.IsNullOrEmpty(trimmed) ? "Object" : trimmed;
    }

    private static List<Param> ExtractParams(ParameterListSyntax? paramList)
    {
        var result = new List<Param>();
        if (paramList is null) return result;
        foreach (var p in paramList.Parameters)
        {
            result.Add(new Param
            {
                Name = p.Identifier.Identifier.Text,
                Type = NonEmptyOrObject(p.AsClause?.Type?.ToString()),
            });
        }
        return result;
    }

    private static int CountBranches(MethodBlockSyntax method)
    {
        var count = 0;
        foreach (var node in method.DescendantNodes())
        {
            switch (node)
            {
                case SingleLineIfStatementSyntax:
                case MultiLineIfBlockSyntax:
                case ElseIfBlockSyntax:
                case WhileBlockSyntax:
                case DoLoopBlockSyntax:
                case ForBlockSyntax:
                case ForEachBlockSyntax:
                    count++;
                    break;
                case CaseBlockSyntax caseBlock:
                    if (!caseBlock.CaseStatement.Cases.Any(c => c is ElseCaseClauseSyntax))
                        count++;
                    break;
            }
        }
        return count;
    }

    private static string? GetContainingTypeName(SyntaxNode node)
    {
        for (var cur = node.Parent; cur is not null; cur = cur.Parent)
        {
            switch (cur)
            {
                case ClassBlockSyntax cb: return cb.ClassStatement.Identifier.Text;
                case ModuleBlockSyntax mb: return mb.ModuleStatement.Identifier.Text;
            }
        }
        return null;
    }

    private static List<string> GetContainingNamespaceParts(SyntaxNode node)
    {
        var parts = new List<string>();
        for (var cur = node.Parent; cur is not null; cur = cur.Parent)
        {
            if (cur is NamespaceBlockSyntax nb)
                parts.Add(nb.NamespaceStatement.Name.ToString());
        }
        parts.Reverse();
        return parts;
    }
}
