using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.VisualBasic;
using Microsoft.CodeAnalysis.VisualBasic.Syntax;

namespace CaseSmith.Mutator;

/// <summary>
/// One candidate mutation site found in a parsed .vb file: the original node,
/// its single-point-mutated replacement, and the manifest metadata for it.
/// Producing the replacement here (not deferring to the caller) keeps the
/// operator tables the single source of truth for "= &lt;-&gt; &lt;&gt;" etc.
/// </summary>
internal sealed class MutationCandidate
{
    public required SyntaxNode TargetNode { get; init; }
    public required SyntaxNode ReplacementNode { get; init; }
    public required string Operator { get; init; }
    public required int Line { get; init; }
    public required string OriginalText { get; init; }
    public required string MutatedText { get; init; }
}

/// <summary>
/// v1 mutation operators: comparison invert, arithmetic swap, boolean flip.
/// Purely syntax-tree based -- every candidate comes from a real
/// BinaryExpressionSyntax/LiteralExpressionSyntax node, so text inside string
/// literals (SQL or otherwise) is never a candidate; Roslyn never parses
/// literal contents as further tokens.
/// </summary>
internal static class MutationOperators
{
    private const string CompareInvert = "compare_invert";
    private const string ArithmeticSwap = "arithmetic_swap";
    private const string BooleanFlip = "boolean_flip";

    // original expression kind -> (replacement expression kind, replacement operator token kind)
    private static readonly Dictionary<SyntaxKind, (SyntaxKind ExprKind, SyntaxKind TokenKind)> CompareMap = new()
    {
        [SyntaxKind.EqualsExpression] = (SyntaxKind.NotEqualsExpression, SyntaxKind.LessThanGreaterThanToken),
        [SyntaxKind.NotEqualsExpression] = (SyntaxKind.EqualsExpression, SyntaxKind.EqualsToken),
        [SyntaxKind.LessThanExpression] = (SyntaxKind.GreaterThanOrEqualExpression, SyntaxKind.GreaterThanEqualsToken),
        [SyntaxKind.GreaterThanOrEqualExpression] = (SyntaxKind.LessThanExpression, SyntaxKind.LessThanToken),
        [SyntaxKind.GreaterThanExpression] = (SyntaxKind.LessThanOrEqualExpression, SyntaxKind.LessThanEqualsToken),
        [SyntaxKind.LessThanOrEqualExpression] = (SyntaxKind.GreaterThanExpression, SyntaxKind.GreaterThanToken),
    };

    private static readonly Dictionary<SyntaxKind, (SyntaxKind ExprKind, SyntaxKind TokenKind)> ArithmeticMap = new()
    {
        [SyntaxKind.AddExpression] = (SyntaxKind.SubtractExpression, SyntaxKind.MinusToken),
        [SyntaxKind.SubtractExpression] = (SyntaxKind.AddExpression, SyntaxKind.PlusToken),
        [SyntaxKind.MultiplyExpression] = (SyntaxKind.IntegerDivideExpression, SyntaxKind.BackslashToken),
        [SyntaxKind.IntegerDivideExpression] = (SyntaxKind.MultiplyExpression, SyntaxKind.AsteriskToken),
    };

    private static readonly Dictionary<SyntaxKind, (SyntaxKind ExprKind, SyntaxKind TokenKind)> BooleanMap = new()
    {
        [SyntaxKind.TrueLiteralExpression] = (SyntaxKind.FalseLiteralExpression, SyntaxKind.FalseKeyword),
        [SyntaxKind.FalseLiteralExpression] = (SyntaxKind.TrueLiteralExpression, SyntaxKind.TrueKeyword),
    };

    /// <summary>
    /// Walks <paramref name="root"/> in document order (deterministic --
    /// DescendantNodes is a stable pre-order traversal) and yields one
    /// candidate per mutable site.
    /// </summary>
    public static IEnumerable<MutationCandidate> FindCandidates(SyntaxNode root)
    {
        foreach (var node in root.DescendantNodes())
        {
            switch (node)
            {
                case BinaryExpressionSyntax bin when CompareMap.TryGetValue(bin.Kind(), out var mapping):
                    yield return BuildBinaryCandidate(bin, mapping, CompareInvert);
                    break;

                case BinaryExpressionSyntax bin when ArithmeticMap.TryGetValue(bin.Kind(), out var mapping):
                    yield return BuildBinaryCandidate(bin, mapping, ArithmeticSwap);
                    break;

                case LiteralExpressionSyntax lit when BooleanMap.TryGetValue(lit.Kind(), out var mapping):
                    yield return BuildLiteralCandidate(lit, mapping);
                    break;
            }
        }
    }

    private static MutationCandidate BuildBinaryCandidate(
        BinaryExpressionSyntax bin, (SyntaxKind ExprKind, SyntaxKind TokenKind) mapping, string op)
    {
        var newOperatorToken = SyntaxFactory.Token(mapping.TokenKind)
            .WithLeadingTrivia(bin.OperatorToken.LeadingTrivia)
            .WithTrailingTrivia(bin.OperatorToken.TrailingTrivia);
        var replacement = SyntaxFactory.BinaryExpression(mapping.ExprKind, bin.Left, newOperatorToken, bin.Right);

        return new MutationCandidate
        {
            TargetNode = bin,
            ReplacementNode = replacement,
            Operator = op,
            Line = bin.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
            OriginalText = bin.ToString(),
            MutatedText = replacement.ToString(),
        };
    }

    private static MutationCandidate BuildLiteralCandidate(
        LiteralExpressionSyntax lit, (SyntaxKind ExprKind, SyntaxKind TokenKind) mapping)
    {
        var newToken = SyntaxFactory.Token(mapping.TokenKind)
            .WithLeadingTrivia(lit.Token.LeadingTrivia)
            .WithTrailingTrivia(lit.Token.TrailingTrivia);
        var replacement = SyntaxFactory.LiteralExpression(mapping.ExprKind, newToken);

        return new MutationCandidate
        {
            TargetNode = lit,
            ReplacementNode = replacement,
            Operator = BooleanFlip,
            Line = lit.GetLocation().GetLineSpan().StartLinePosition.Line + 1,
            OriginalText = lit.ToString(),
            MutatedText = replacement.ToString(),
        };
    }
}
