Namespace CaseSmith.Fixtures.Mutator

    ''' <summary>
    ''' Exercises all three v1 mutation operators plus a SQL string literal
    ''' that must NOT be mutated -- the "=" and "+" inside it are text, not
    ''' syntax nodes.
    ''' </summary>
    Public Class RiskEngine

        Public Function IsEligible(score As Integer, threshold As Integer) As Boolean
            Dim sql As String = "SELECT * FROM T_ACCOUNT WHERE SCORE = 1 AND BALANCE + 10 > 0"
            If score >= threshold Then
                Return True
            End If
            Return False
        End Function

        Public Function Combine(a As Integer, b As Integer) As Integer
            Dim total As Integer = a + b
            Dim diff As Integer = a - b
            Dim product As Integer = a * b
            Dim quotient As Integer = a \ b
            Return total
        End Function

        Public Function Flag() As Boolean
            Return True
        End Function

    End Class

End Namespace
