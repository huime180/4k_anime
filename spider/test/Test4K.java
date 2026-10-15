import com.github.catvod.spider.Quark4K;
import java.util.*;

/** 本地跑一遍 spider：确认真能拿到「原画 / 智能」两条可播地址 */
public class Test4K {
    public static void main(String[] args) throws Exception {
        String id = args.length > 0 ? args[0] : "fef3dd82b3eb";
        Quark4K s = new Quark4K();
        String ext = "{\"data\":\"http://127.0.0.1:8787/anime.json\"}";
        s.init(null, ext);
        System.out.println("home: " + cut(s.homeContent(false), 160));
        String detail = s.detailContent(Arrays.asList("4k:" + id));
        System.out.println("detail: " + cut(detail, 700));
        int pf = detail.indexOf("\"vod_play_from\":\"");
        String from = detail.substring(pf + 17, detail.indexOf("\"", pf + 17));
        System.out.println("play_from = " + from);
        int pu = detail.indexOf("\"vod_play_url\":\"");
        String urls = detail.substring(pu + 17, detail.indexOf("\"}", pu + 17));
        String[] groups = urls.split("\\$\\$\\$");
        System.out.println("groups = " + groups.length);
        for (int g = 0; g < groups.length; g++) {
            String flag = from.split("\\$\\$\\$")[g];
            String first = groups[g].split("#")[0];
            String pid = first.substring(first.indexOf("$") + 1);
            System.out.println("---- flag=" + flag + "  ep=" + first.substring(0, first.indexOf("$")) + "  pid=" + pid);
            long t0 = System.currentTimeMillis();
            String pc = s.playerContent(flag, pid, null);
            System.out.println("   (" + (System.currentTimeMillis() - t0) + "ms) " + cut(pc, 420));
            int ui = pc.indexOf("\"url\":\"");
            int hi = pc.indexOf("\",\"header\":\"");
            if (ui > 0 && hi > ui) {
                String u = pc.substring(ui + 7, pc.indexOf("\"", ui + 7)).replace("\\/", "/");
                String h = pc.substring(hi + 12, pc.length() - 2).replace("\\n", "\n").replace("\\\"", "\"");
                java.io.PrintWriter w = new java.io.PrintWriter("work/probe_" + g + ".txt", "UTF-8");
                w.println(u); w.println("---HDR---"); w.print(h); w.close();
                System.out.println("   -> work/probe_" + g + ".txt");
            }
        }
    }
    static String cut(String s, int n) { return s == null ? "null" : (s.length() <= n ? s : s.substring(0, n) + "…"); }
}
