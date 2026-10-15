import com.github.catvod.spider.Anime4KGuard;
import java.util.Arrays;
public class DumpDetail {
    public static void main(String[] a) {
        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{\"data\":\"https://huime180.github.io/4k_anime/anime.json\"}");
        System.out.println(s.detailContent(Arrays.asList("4k:" + (a.length > 0 ? a[0] : "fef3dd82b3eb"))));
    }
}
