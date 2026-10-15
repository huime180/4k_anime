import com.github.catvod.spider.Anime4KGuard;
public class DumpHome {
    public static void main(String[] a) {
        Anime4KGuard s = new Anime4KGuard();
        s.init(null, "{\"data\":\"https://huime180.github.io/4k_anime/anime.json\"}");
        System.out.println(s.homeContent(false));
    }
}
