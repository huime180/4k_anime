import com.github.catvod.spider.Anime4KGuard;
import java.util.Arrays;
public class DumpDetailFb {
    public static void main(String[] a) {
        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{\"data\":\"http://127.0.0.1:8787/anime.json\",\"fallback\":true}");
        System.out.println(s.detailContent(Arrays.asList("4k:" + (a.length > 0 ? a[0] : "fef3dd82b3eb"))));
    }
}
