/**
 * Fake System-Under-Test — CaseSmith 開發用替身。
 *
 * 真正的受測物是使用者公司側的 VB.NET .exe(讀寫 DB2);這支只複製其
 * 可觀察行為形狀(JDBC 讀寫 + stdout + exit code),供 golden master
 * 流程與 ARTF shell_command runtime 的整合開發。不代表任何真實業務。
 *
 * 用法(java 單檔原始碼模式,不需編譯):
 *   export JDBC_CONNECTION='jdbc:db2://localhost:50000/TESTDB:user=...;password=...;'
 *   java -cp <jcc.jar> sut/FakeSut.java update-order-status <orderId> <statusCd>
 *   java -cp <jcc.jar> sut/FakeSut.java get-active-customer <custId>
 *
 * exit code:0=成功、2=目標列不存在、64=用法錯、1=其他錯誤。
 */

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;

public class FakeSut {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: FakeSut <update-order-status|get-active-customer> <args...>");
            System.exit(64);
        }
        String url = System.getenv("JDBC_CONNECTION");
        if (url == null || url.isBlank()) {
            System.err.println("JDBC_CONNECTION not set");
            System.exit(64);
        }
        try (Connection conn = DriverManager.getConnection(url)) {
            switch (args[0]) {
                case "update-order-status" -> updateOrderStatus(conn, args);
                case "get-active-customer" -> getActiveCustomer(conn, args);
                default -> {
                    System.err.println("unknown command: " + args[0]);
                    System.exit(64);
                }
            }
        }
    }

    /** 對齊 spec card 的 UpdateOrderStatus:UPDATE T_ORDER SET STATUS_CD WHERE ORDER_ID。 */
    private static void updateOrderStatus(Connection conn, String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println("usage: update-order-status <orderId> <statusCd>");
            System.exit(64);
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "UPDATE APP.T_ORDER SET STATUS_CD = ? WHERE ORDER_ID = ?")) {
            ps.setString(1, args[2]);
            ps.setLong(2, Long.parseLong(args[1]));
            int affected = ps.executeUpdate();
            System.out.println("updated_rows=" + affected);
            if (affected == 0) {
                System.exit(2);
            }
        }
    }

    /** 對齊 spec card 的 GetActiveCustomer:讀取並印出,唯讀。 */
    private static void getActiveCustomer(Connection conn, String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("usage: get-active-customer <custId>");
            System.exit(64);
        }
        try (PreparedStatement ps = conn.prepareStatement(
                "SELECT CUST_NM, COUNTRY_CD FROM APP.T_CUSTOMER WHERE CUST_ID = ?")) {
            ps.setLong(1, Long.parseLong(args[1]));
            try (ResultSet rs = ps.executeQuery()) {
                if (!rs.next()) {
                    System.out.println("customer=none");
                    System.exit(2);
                }
                System.out.println("customer=" + rs.getString(1) + " country=" + rs.getString(2));
            }
        }
    }
}
