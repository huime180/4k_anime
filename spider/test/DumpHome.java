import com.github.catvod.spider.Anime4KGuard;
public class DumpHome {
    public static void main(String[] a) {
        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{\"data\":\"http://127.0.0.1:8787/anime.json\"}");
        System.out.println(s.homeContent(false));
    }
}
