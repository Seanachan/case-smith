using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.VisualBasic;
using Microsoft.CodeAnalysis.VisualBasic.Syntax;

namespace CaseSmith.Extractor;

/// <summary>
/// Syntax-level HTTP endpoint extraction: WebRequest.Create / New Uri /
/// HttpClient's GetAsync|PostAsync|PutAsync|DeleteAsync / WebClient's
/// DownloadString|UploadString, matched on constant string-literal arguments
/// only (see docs/CONTRACTS.md, spec card contract v1, §7).
/// </summary>
internal static class EndpointAnalyzer
{
    private static readonly Dictionary<string, string> MethodNameToHttpMethod = new(StringComparer.Ordinal)
    {
        ["Create"] = "GET",
        ["DownloadString"] = "GET",
        ["UploadString"] = "POST",
        ["GetAsync"] = "GET",
        ["PostAsync"] = "POST",
        ["PutAsync"] = "PUT",
        ["DeleteAsync"] = "DELETE",
    };

    public static List<Endpoint> Analyze(MethodBlockSyntax method)
    {
        var endpoints = new List<Endpoint>();

        foreach (var invocation in method.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (invocation.Expression is not MemberAccessExpressionSyntax mae) continue;
            var calledName = mae.Name.Identifier.Text;
            if (!MethodNameToHttpMethod.TryGetValue(calledName, out var httpMethod)) continue;

            // "Create" is only an endpoint trigger when called on WebRequest,
            // e.g. WebRequest.Create("..."); other ".Create(...)" calls are noise.
            if (calledName == "Create" &&
                !(mae.Expression is IdentifierNameSyntax recv && recv.Identifier.Text == "WebRequest"))
            {
                continue;
            }

            var url = FirstStringLiteralArgument(invocation.ArgumentList);
            if (url is null) continue;
            endpoints.Add(new Endpoint { HttpMethod = httpMethod, Url = url });
        }

        foreach (var creation in method.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
        {
            var lastSegment = creation.Type.ToString().Split('.').Last();
            if (lastSegment != "Uri") continue;
            var url = FirstStringLiteralArgument(creation.ArgumentList);
            if (url is null) continue;
            endpoints.Add(new Endpoint { HttpMethod = "GET", Url = url });
        }

        return endpoints;
    }

    private static string? FirstStringLiteralArgument(ArgumentListSyntax? argumentList)
    {
        if (argumentList is null || argumentList.Arguments.Count == 0) return null;
        if (argumentList.Arguments[0] is not SimpleArgumentSyntax arg) return null;
        if (arg.Expression is not LiteralExpressionSyntax lit) return null;
        if (lit.Kind() != SyntaxKind.StringLiteralExpression) return null;
        return lit.Token.ValueText;
    }
}
