Imports System.Data.SqlClient

Namespace CaseSmith.Fixtures.Dao

    ''' <summary>
    ''' Single-table CRUD against T_CUSTOMER. Constant SQL only, no concatenation.
    ''' </summary>
    Public Class CustomerRepository

        Public Function GetActiveCustomer(custId As Integer) As Object
            Dim sql As String = "SELECT CUST_ID, CUST_NM FROM T_CUSTOMER WHERE CUST_ID = ? AND COUNTRY_CD = ?"
            Dim cmd As New SqlCommand(sql)
            Return cmd
        End Function

        Public Sub UpdateCustomerName(custId As Integer, name As String)
            Dim cmd As New SqlCommand()
            cmd.CommandText = "UPDATE T_CUSTOMER SET CUST_NM = ? WHERE CUST_ID = ?"
        End Sub

        Public Sub InsertCustomer(custId As Integer, name As String)
            Dim cmd As New SqlCommand("INSERT INTO T_CUSTOMER (CUST_ID, CUST_NM) VALUES (?, ?)")
        End Sub

        Public Sub DeleteCustomer(custId As Integer)
            Dim cmd As New SqlCommand("DELETE FROM T_CUSTOMER WHERE CUST_ID = ?")
        End Sub

        ''' <summary>No SQL. Untyped parameter -- exercises the "As" defaulting to Object.</summary>
        Public Sub Touch(id)
        End Sub

    End Class

End Namespace
