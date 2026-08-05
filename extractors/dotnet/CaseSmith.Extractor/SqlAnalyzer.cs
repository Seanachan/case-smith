using System.Text;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.VisualBasic;
using Microsoft.CodeAnalysis.VisualBasic.Syntax;

namespace CaseSmith.Extractor;

/// <summary>
/// Syntax-level SQL text collection + regex-based table/column extraction for
/// one method body. No semantic model / MSBuildWorkspace -- only constant
/// string literals, "&amp;" concatenation, and single-assignment local
/// variables are traced (see docs/CONTRACTS.md, spec card contract v1).
/// </summary>
internal static class SqlAnalyzer
{
    private static readonly string[] CommandTypeNames =
        { "SqlCommand", "OleDbCommand", "OdbcCommand", "iDB2Command" };

    public sealed class Result
    {
        public Dictionary<string, SortedSet<string>> Tables { get; } = new();
        public SortedSet<string> ConditionColumns { get; } = new(StringComparer.Ordinal);
        public SortedSet<string> UnqualifiedConditionColumns { get; } = new(StringComparer.Ordinal);
        public bool DynamicSql { get; set; }
    }

    public static Result Analyze(MethodBlockSyntax method)
    {
        var result = new Result();
        var varInit = CollectSingleAssignmentLocals(method);
        var visited = new HashSet<SyntaxNode>();
        var roots = new List<ExpressionSyntax>();

        // Trigger 1: SqlCommand/OleDbCommand/OdbcCommand/iDB2Command constructor's first argument.
        foreach (var creation in method.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
        {
            if (!IsCommandType(creation.Type)) continue;
            var args = creation.ArgumentList?.Arguments;
            if (args is null || args.Value.Count == 0) continue;
            if (args.Value[0] is SimpleArgumentSyntax firstArg)
                roots.Add(firstArg.Expression);
        }

        // Trigger 2: `.CommandText = ...` assignment.
        foreach (var assign in method.DescendantNodes().OfType<AssignmentStatementSyntax>())
        {
            if (assign.Left is MemberAccessExpressionSyntax mae &&
                mae.Name.Identifier.Text.Equals("CommandText", StringComparison.Ordinal))
            {
                roots.Add(assign.Right);
            }
        }

        foreach (var root in roots)
        {
            var (text, dynamic) = Flatten(root, varInit, visited);
            if (!string.IsNullOrWhiteSpace(text)) MergeSqlText(result, text);
            if (dynamic) result.DynamicSql = true;
        }

        // Trigger 3: any remaining string literal that looks like SQL on its own
        // (SELECT/INSERT/UPDATE/DELETE prefix), not already covered above.
        foreach (var lit in method.DescendantNodes().OfType<LiteralExpressionSyntax>())
        {
            if (lit.Kind() != SyntaxKind.StringLiteralExpression) continue;
            if (visited.Contains(lit)) continue;
            var value = lit.Token.ValueText;
            if (!LooksLikeSql(value)) continue;

            // Widen to the top of any surrounding "&" concatenation chain so the
            // whole statement (including non-constant parts) is captured.
            SyntaxNode current = lit;
            while (current.Parent is BinaryExpressionSyntax bin &&
                   bin.OperatorToken.IsKind(SyntaxKind.AmpersandToken) &&
                   (bin.Left == current || bin.Right == current))
            {
                current = bin;
            }
            if (visited.Contains(current)) continue;

            var (text, dynamic) = Flatten((ExpressionSyntax)current, varInit, visited);
            if (!string.IsNullOrWhiteSpace(text)) MergeSqlText(result, text);
            if (dynamic) result.DynamicSql = true;
        }

        return result;
    }

    private static bool LooksLikeSql(string value)
    {
        var trimmed = value.TrimStart().ToUpperInvariant();
        return trimmed.StartsWith("SELECT", StringComparison.Ordinal) ||
               trimmed.StartsWith("INSERT", StringComparison.Ordinal) ||
               trimmed.StartsWith("UPDATE", StringComparison.Ordinal) ||
               trimmed.StartsWith("DELETE", StringComparison.Ordinal);
    }

    private static bool IsCommandType(TypeSyntax type)
    {
        var text = type.ToString();
        var lastSegment = text.Split('.').Last();
        return CommandTypeNames.Contains(lastSegment, StringComparer.Ordinal);
    }

    /// <summary>
    /// Local variables declared with a single `Dim x As T = "..."` and never
    /// reassigned afterward -- "同方法內單次指派可追" in the spec.
    /// </summary>
    private static Dictionary<string, ExpressionSyntax> CollectSingleAssignmentLocals(MethodBlockSyntax method)
    {
        var map = new Dictionary<string, ExpressionSyntax>(StringComparer.Ordinal);
        var excluded = new HashSet<string>(StringComparer.Ordinal);

        foreach (var decl in method.DescendantNodes().OfType<LocalDeclarationStatementSyntax>())
        {
            foreach (var declarator in decl.Declarators)
            {
                if (declarator.Initializer is null) continue;
                foreach (var name in declarator.Names)
                {
                    var id = name.Identifier.Text;
                    if (excluded.Contains(id)) continue;
                    if (map.ContainsKey(id))
                    {
                        map.Remove(id);
                        excluded.Add(id);
                        continue;
                    }
                    map[id] = declarator.Initializer.Value;
                }
            }
        }

        foreach (var assign in method.DescendantNodes().OfType<AssignmentStatementSyntax>())
        {
            if (assign.Left is IdentifierNameSyntax id)
            {
                var name = id.Identifier.Text;
                if (map.ContainsKey(name))
                {
                    map.Remove(name);
                    excluded.Add(name);
                }
            }
        }

        return map;
    }

    /// <summary>
    /// Walks an expression tree, resolving single-assignment local variables and
    /// flattening "&amp;" concatenation into a constant text. Any non-constant
    /// sub-expression (parameter, method call, unresolved variable, ...) sets
    /// <c>dynamic</c> = true and contributes nothing to the text.
    /// </summary>
    private static (string text, bool dynamic) Flatten(
        ExpressionSyntax root, Dictionary<string, ExpressionSyntax> varInit, HashSet<SyntaxNode> visited)
    {
        var sb = new StringBuilder();
        var dynamic = false;
        var resolving = new HashSet<string>(StringComparer.Ordinal);

        void Walk(ExpressionSyntax expr)
        {
            if (expr is ParenthesizedExpressionSyntax paren)
            {
                Walk(paren.Expression);
                return;
            }

            if (expr is IdentifierNameSyntax id && varInit.TryGetValue(id.Identifier.Text, out var init))
            {
                var name = id.Identifier.Text;
                if (resolving.Contains(name))
                {
                    dynamic = true; // cyclic reference guard
                    return;
                }
                resolving.Add(name);
                visited.Add(id);
                foreach (var n in init.DescendantNodesAndSelf()) visited.Add(n);
                Walk(init);
                return;
            }

            if (expr is BinaryExpressionSyntax bin && bin.OperatorToken.IsKind(SyntaxKind.AmpersandToken))
            {
                Walk(bin.Left);
                Walk(bin.Right);
                return;
            }

            if (expr is LiteralExpressionSyntax lit && lit.Kind() == SyntaxKind.StringLiteralExpression)
            {
                sb.Append(lit.Token.ValueText);
                visited.Add(lit);
                return;
            }

            dynamic = true;
        }

        visited.Add(root);
        foreach (var n in root.DescendantNodesAndSelf()) visited.Add(n);
        Walk(root);
        return (sb.ToString(), dynamic);
    }

    // --- regex-based table / condition-column extraction -------------------

    private const string TableName = @"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?";
    private static readonly Regex DeleteFromRe = new(@"\bDELETE\s+FROM\s+(" + TableName + ")", RegexOptions.IgnoreCase);
    private static readonly Regex InsertIntoRe = new(@"\bINSERT\s+INTO\s+(" + TableName + ")", RegexOptions.IgnoreCase);
    private static readonly Regex UpdateRe = new(@"\bUPDATE\s+(" + TableName + ")", RegexOptions.IgnoreCase);
    private static readonly Regex FromJoinRe = new(@"\b(?:FROM|JOIN)\s+(" + TableName + ")", RegexOptions.IgnoreCase);
    private static readonly Regex WhereBodyRe = new(
        @"\bWHERE\b(.*?)(?:\bORDER\s+BY\b|\bGROUP\s+BY\b|\bHAVING\b|$)", RegexOptions.IgnoreCase | RegexOptions.Singleline);
    private static readonly Regex OnBodyRe = new(
        @"\bON\b(.*?)(?:\bWHERE\b|\bINNER\s+JOIN\b|\bLEFT\s+JOIN\b|\bRIGHT\s+JOIN\b|\bFULL\s+JOIN\b|\bJOIN\b|\bORDER\s+BY\b|\bGROUP\s+BY\b|$)",
        RegexOptions.IgnoreCase | RegexOptions.Singleline);
    private static readonly Regex ConditionLhsRe = new(
        @"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\s*(?:<=|>=|<>|=|<|>|\bLIKE\b|\bIN\b)",
        RegexOptions.IgnoreCase);

    private static void MergeSqlText(Result result, string sqlText)
    {
        var tablesInText = new Dictionary<string, SortedSet<string>>(StringComparer.Ordinal);
        var masked = new StringBuilder(sqlText);

        void Blank(Match m)
        {
            for (var i = m.Index; i < m.Index + m.Length; i++) masked[i] = ' ';
        }

        void AddOp(string rawTable, string op)
        {
            var table = StripSchema(rawTable);
            if (!tablesInText.TryGetValue(table, out var ops))
            {
                ops = new SortedSet<string>(StringComparer.Ordinal);
                tablesInText[table] = ops;
            }
            ops.Add(op);
        }

        foreach (Match m in DeleteFromRe.Matches(sqlText))
        {
            AddOp(m.Groups[1].Value, "DELETE");
            Blank(m);
        }
        foreach (Match m in InsertIntoRe.Matches(sqlText))
        {
            AddOp(m.Groups[1].Value, "INSERT");
            Blank(m);
        }
        foreach (Match m in UpdateRe.Matches(masked.ToString()))
        {
            AddOp(m.Groups[1].Value, "UPDATE");
            Blank(m);
        }
        foreach (Match m in FromJoinRe.Matches(masked.ToString()))
        {
            AddOp(m.Groups[1].Value, "SELECT");
        }

        var isSingleTable = tablesInText.Count == 1;
        var soleTable = isSingleTable ? tablesInText.Keys.Single() : null;

        var conditionBodies = new List<string>();
        var whereMatch = WhereBodyRe.Match(sqlText);
        if (whereMatch.Success) conditionBodies.Add(whereMatch.Groups[1].Value);
        foreach (Match m in OnBodyRe.Matches(sqlText)) conditionBodies.Add(m.Groups[1].Value);

        foreach (var body in conditionBodies)
        {
            foreach (Match m in ConditionLhsRe.Matches(body))
            {
                var col = m.Groups[1].Value;
                if (col.Contains('.'))
                {
                    result.ConditionColumns.Add(col);
                }
                else if (isSingleTable)
                {
                    result.ConditionColumns.Add($"{soleTable}.{col}");
                }
                else
                {
                    result.UnqualifiedConditionColumns.Add(col);
                }
            }
        }

        foreach (var (table, ops) in tablesInText)
        {
            if (!result.Tables.TryGetValue(table, out var existing))
            {
                existing = new SortedSet<string>(StringComparer.Ordinal);
                result.Tables[table] = existing;
            }
            existing.UnionWith(ops);
        }
    }

    private static string StripSchema(string qualified)
    {
        var idx = qualified.LastIndexOf('.');
        return idx < 0 ? qualified : qualified[(idx + 1)..];
    }
}
