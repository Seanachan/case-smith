Imports System.Net

Namespace CaseSmith.Fixtures.Ops

    ''' <summary>
    ''' No SQL in this file. Exercises branch_count (Select Case / nested If /
    ''' ElseIf / For Each), HTTP endpoints (WebRequest.Create -&gt; GET,
    ''' WebClient.UploadString -&gt; POST), and a branch-free / SQL-free method.
    ''' </summary>
    Public Class OrderProcessor

        Public Function ClassifyOrder(statusCd As String, qty As Integer) As String
            Dim result As String = ""

            Select Case statusCd
                Case "A"
                    result = "ACTIVE"
                Case "P", "H"
                    result = "PENDING"
                Case Else
                    result = "UNKNOWN"
            End Select

            If qty > 100 Then
                If statusCd = "A" Then
                    result &= "_BULK"
                End If
            ElseIf qty > 10 Then
                result &= "_MEDIUM"
            End If

            For Each ch As Char In statusCd
                If ch = "X"c Then
                    result &= "_FLAGGED"
                End If
            Next

            Return result
        End Function

        Public Sub NotifyOrderCreated(orderId As Integer)
            Dim client As New WebClient()
            client.UploadString("https://api.example.internal/orders/notify", "POST")
        End Sub

        Public Function FetchOrderStatus(orderId As Integer) As String
            Dim req As WebRequest = WebRequest.Create("https://api.example.internal/orders/status")
            Return req.ToString()
        End Function

        ''' <summary>No SQL, no branches, no endpoints -- an empty card is legal.</summary>
        Public Sub NoOp()
        End Sub

    End Class

End Namespace
