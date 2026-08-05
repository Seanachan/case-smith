using CaseSmith.Extractor;
using Microsoft.CodeAnalysis.VisualBasic;
using Xunit;

namespace CaseSmith.Extractor.Tests;

/// <summary>
/// Structural assertions against extractor output for each Fixtures/*.vb file
/// -- not just "did it not throw". Field values are checked one by one so a
/// regression in table/column/branch extraction shows up as a specific
/// assertion failure, not a silent shape drift.
/// </summary>
public class ExtractorTests
{
    private static readonly string FixturesDir = Path.Combine(AppContext.BaseDirectory, "Fixtures");

    private static List<MethodCard> ExtractFile(string fileName)
    {
        var path = Path.Combine(FixturesDir, fileName);
        var text = File.ReadAllText(path);
        var tree = VisualBasicSyntaxTree.ParseText(text, path: path);
        return MethodExtractor.ExtractMethods(tree, fileName).ToList();
    }

    private static MethodCard Find(List<MethodCard> methods, string methodName) =>
        methods.Single(m => m.Id.EndsWith("." + methodName, StringComparison.Ordinal));

    // ---------------- SingleTableCrud.vb ----------------

    [Fact]
    public void SingleTableCrud_ProducesFiveMethods()
    {
        Assert.Equal(5, ExtractFile("SingleTableCrud.vb").Count);
    }

    [Fact]
    public void GetActiveCustomer_SelectsFromSingleTable_WithQualifiedConditionColumns()
    {
        var m = Find(ExtractFile("SingleTableCrud.vb"), "GetActiveCustomer");

        Assert.Equal("CaseSmith.Fixtures.Dao.CustomerRepository.GetActiveCustomer", m.Id);
        Assert.Equal("SingleTableCrud.vb", m.File);
        Assert.Equal("GetActiveCustomer", m.Signature.Name);
        Assert.Equal("Object", m.Signature.Returns);
        var p = Assert.Single(m.Signature.Params);
        Assert.Equal("custId", p.Name);
        Assert.Equal("Integer", p.Type);
        Assert.False(m.DynamicSql);
        Assert.Equal(0, m.BranchCount);

        var table = Assert.Single(m.Tables);
        Assert.Equal("T_CUSTOMER", table.Name);
        Assert.Equal(new[] { "SELECT" }, table.Operations);

        Assert.Equal(new[] { "T_CUSTOMER.COUNTRY_CD", "T_CUSTOMER.CUST_ID" }, m.ConditionColumns);
        Assert.Empty(m.UnqualifiedConditionColumns);
        Assert.Empty(m.Endpoints);
    }

    [Fact]
    public void UpdateCustomerName_UsesCommandTextAssignment()
    {
        var m = Find(ExtractFile("SingleTableCrud.vb"), "UpdateCustomerName");

        var table = Assert.Single(m.Tables);
        Assert.Equal("T_CUSTOMER", table.Name);
        Assert.Equal(new[] { "UPDATE" }, table.Operations);
        Assert.Equal(new[] { "T_CUSTOMER.CUST_ID" }, m.ConditionColumns);
        Assert.False(m.DynamicSql);
        Assert.Equal("", m.Signature.Returns);
    }

    [Fact]
    public void InsertCustomer_ConstructorArgument_HasNoConditionColumns()
    {
        var m = Find(ExtractFile("SingleTableCrud.vb"), "InsertCustomer");

        var table = Assert.Single(m.Tables);
        Assert.Equal("T_CUSTOMER", table.Name);
        Assert.Equal(new[] { "INSERT" }, table.Operations);
        Assert.Empty(m.ConditionColumns);
        Assert.Empty(m.UnqualifiedConditionColumns);
    }

    [Fact]
    public void DeleteCustomer_MatchesDeleteFromPattern()
    {
        var m = Find(ExtractFile("SingleTableCrud.vb"), "DeleteCustomer");

        var table = Assert.Single(m.Tables);
        Assert.Equal("T_CUSTOMER", table.Name);
        Assert.Equal(new[] { "DELETE" }, table.Operations);
        Assert.Equal(new[] { "T_CUSTOMER.CUST_ID" }, m.ConditionColumns);
    }

    [Fact]
    public void Touch_HasNoSqlAndUntypedParamDefaultsToObject()
    {
        var m = Find(ExtractFile("SingleTableCrud.vb"), "Touch");

        Assert.Empty(m.Tables);
        Assert.Empty(m.ConditionColumns);
        Assert.Empty(m.UnqualifiedConditionColumns);
        Assert.Empty(m.Endpoints);
        Assert.Equal(0, m.BranchCount);
        Assert.False(m.DynamicSql);
        var p = Assert.Single(m.Signature.Params);
        Assert.Equal("id", p.Name);
        Assert.Equal("Object", p.Type);
        Assert.Equal("", m.Signature.Returns);
    }

    // ---------------- MultiTableJoin.vb ----------------

    [Fact]
    public void FindOrdersByStatus_JoinWithConcatenation_MarksDynamicAndUnqualifiedColumns()
    {
        var methods = ExtractFile("MultiTableJoin.vb");
        var m = Assert.Single(methods);

        Assert.Equal("CaseSmith.Fixtures.Dao.OrderQueryService.FindOrdersByStatus", m.Id);
        Assert.True(m.DynamicSql);

        Assert.Equal(2, m.Tables.Count);
        Assert.Equal("T_CUSTOMER", m.Tables[0].Name);
        Assert.Equal(new[] { "SELECT" }, m.Tables[0].Operations);
        Assert.Equal("T_ORDER", m.Tables[1].Name);
        Assert.Equal(new[] { "SELECT" }, m.Tables[1].Operations);

        Assert.Empty(m.ConditionColumns);
        Assert.Equal(new[] { "CUST_ID", "STATUS_CD" }, m.UnqualifiedConditionColumns);
    }

    // ---------------- MixedFeatures.vb ----------------

    [Fact]
    public void MixedFeatures_ProducesFourMethods()
    {
        Assert.Equal(4, ExtractFile("MixedFeatures.vb").Count);
    }

    [Fact]
    public void ClassifyOrder_CountsSelectCaseNestedIfElseIfAndForEach()
    {
        var m = Find(ExtractFile("MixedFeatures.vb"), "ClassifyOrder");

        // 2 Case blocks (Case Else excluded) + outer If + nested If + ElseIf
        // + For Each + If nested inside the For Each = 7.
        Assert.Equal(7, m.BranchCount);
        Assert.Equal("String", m.Signature.Returns);
        Assert.Empty(m.Tables);
        Assert.Empty(m.Endpoints);
        Assert.False(m.DynamicSql);
    }

    [Fact]
    public void NotifyOrderCreated_UploadStringMapsToPost()
    {
        var m = Find(ExtractFile("MixedFeatures.vb"), "NotifyOrderCreated");

        var ep = Assert.Single(m.Endpoints);
        Assert.Equal("POST", ep.HttpMethod);
        Assert.Equal("https://api.example.internal/orders/notify", ep.Url);
        Assert.Equal(0, m.BranchCount);
        Assert.Empty(m.Tables);
    }

    [Fact]
    public void FetchOrderStatus_WebRequestCreateMapsToGet()
    {
        var m = Find(ExtractFile("MixedFeatures.vb"), "FetchOrderStatus");

        var ep = Assert.Single(m.Endpoints);
        Assert.Equal("GET", ep.HttpMethod);
        Assert.Equal("https://api.example.internal/orders/status", ep.Url);
    }

    [Fact]
    public void NoOp_IsAnEmptyButValidCard()
    {
        var m = Find(ExtractFile("MixedFeatures.vb"), "NoOp");

        Assert.Equal(0, m.BranchCount);
        Assert.Empty(m.Tables);
        Assert.Empty(m.ConditionColumns);
        Assert.Empty(m.UnqualifiedConditionColumns);
        Assert.Empty(m.Endpoints);
        Assert.False(m.DynamicSql);
        Assert.Equal("", m.Signature.Returns);
        Assert.Empty(m.Signature.Params);
    }

    // ---------------- whole-directory determinism ----------------

    [Fact]
    public void AllFixtures_ProduceTenMethodsSortedById()
    {
        var files = Directory.GetFiles(FixturesDir, "*.vb", SearchOption.AllDirectories)
            .OrderBy(f => f, StringComparer.Ordinal);

        var methods = new List<MethodCard>();
        foreach (var f in files)
        {
            var tree = VisualBasicSyntaxTree.ParseText(File.ReadAllText(f), path: f);
            methods.AddRange(MethodExtractor.ExtractMethods(tree, Path.GetFileName(f)));
        }
        methods = methods.OrderBy(m => m.Id, StringComparer.Ordinal).ToList();

        Assert.Equal(13, methods.Count);  // 10 + CallGraph.vb 的 3 個
        var ids = methods.Select(m => m.Id).ToList();
        Assert.Equal(ids.OrderBy(x => x, StringComparer.Ordinal).ToList(), ids);
    }

    [Fact]
    public void AllFixtures_EveryCardHasEmptySummaryField()
    {
        var files = Directory.GetFiles(FixturesDir, "*.vb", SearchOption.AllDirectories)
            .OrderBy(f => f, StringComparer.Ordinal);

        var methods = new List<MethodCard>();
        foreach (var f in files)
        {
            var tree = VisualBasicSyntaxTree.ParseText(File.ReadAllText(f), path: f);
            methods.AddRange(MethodExtractor.ExtractMethods(tree, Path.GetFileName(f)));
        }

        Assert.NotEmpty(methods);
        Assert.All(methods, m => Assert.Equal("", m.Summary));
    }

    // ---------------- CallGraph.vb ----------------

    [Fact]
    public void SettleOrder_CollectsCalls_SortedAndDeduplicated()
    {
        var m = Find(ExtractFile("CallGraph.vb"), "SettleOrder");
        Assert.Equal(new List<string> { "LoadCustomer", "WriteLog" }, m.Calls);
    }

    [Fact]
    public void SettleOrder_LocalArrayIndexing_IsNotACall()
    {
        var m = Find(ExtractFile("CallGraph.vb"), "SettleOrder");
        Assert.DoesNotContain("amounts", m.Calls);
    }

    [Fact]
    public void LeafMethod_HasEmptyCalls()
    {
        Assert.Empty(Find(ExtractFile("CallGraph.vb"), "WriteLog").Calls);
    }
}
