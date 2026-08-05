Imports System.Data.OleDb

Namespace CaseSmith.Fixtures.Dao

    ''' <summary>
    ''' Multi-table JOIN built with "&amp;" concatenation, one variable
    ''' interpolation (non-constant) -&gt; dynamic_sql: true, and bare
    ''' (unqualified) condition columns on both the ON and WHERE clauses.
    ''' </summary>
    Public Class OrderQueryService

        Public Function FindOrdersByStatus(statusCd As String) As Object
            Dim sql As String = "SELECT ORDER_ID, CUST_NM FROM T_ORDER JOIN T_CUSTOMER ON CUST_ID = CUST_ID WHERE STATUS_CD = " & statusCd
            Dim cmd As New OleDbCommand(sql)
            Return cmd
        End Function

    End Class

End Namespace
