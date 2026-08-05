' Call-graph fixture: intra-file calls, member-access calls, and the VB
' parentheses trap (local array indexing must NOT be reported as a call).
Namespace CaseSmith.Fixtures.Blocks

    Public Class SettlementFlow

        Public Sub SettleOrder(orderId As Decimal)
            LoadCustomer(orderId)
            Dim helper As New AuditHelper()
            helper.WriteLog("settle")
            Dim amounts(10) As Integer
            Dim first As Integer = amounts(0)
        End Sub

        Public Sub LoadCustomer(custId As Decimal)
            Dim sql As String = "SELECT CUST_NM FROM T_CUSTOMER WHERE CUST_ID = ?"
        End Sub

    End Class

    Public Class AuditHelper

        Public Sub WriteLog(msg As String)
        End Sub

    End Class

End Namespace
