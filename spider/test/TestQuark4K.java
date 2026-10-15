import com.github.catvod.spider.Quark4K;
import java.util.*;
public class TestQuark4K {
    public static void main(String[] a) throws Exception {
        String id = a.length > 0 ? a[0] : "fef3dd82b3eb";
        Quark4K s = new Quark4K();
        s.init(null, "{\"data\":\"http://127.0.0.1:8787/anime.json\"}");
        String d = s.detailContent(Arrays.asList("4k:" + id));
        int pf = d.indexOf("\"vod_play_from\":\"");
        int pu = d.indexOf("\"vod_play_url\":\"");
        System.out.println("from: " + d.substring(pf + 17, d.indexOf("\"", pf + 17)));
        System.out.println("msg : " + (d.contains("\"msg\"") ? d.substring(d.indexOf("\"msg\""), Math.min(d.length(), d.indexOf("\"msg\"") + 160)) : "(有列表)"));
        if (pu > 0) {
            String urls = d.substring(pu + 17, d.indexOf("\"}", pu + 17));
            String g0 = urls.split("\\$\\$\\$")[0].split("#")[0];
            String pid = g0.substring(g0.indexOf("$") + 1);
            System.out.println("play: " + s.playerContent("夸父原", pid, null).substring(0, 240));
        }
    }
}
