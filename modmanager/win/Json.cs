using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Cap2ModManager
{
    /// <summary>cap2mod.py info 출력을 읽기 위한 최소 JSON 파서 (객체 → Dictionary, 배열 → List).</summary>
    internal static class Json
    {
        public static object Parse(string s)
        {
            int i = 0;
            var v = Value(s, ref i);
            Ws(s, ref i);
            if (i != s.Length) throw new FormatException("JSON 뒤에 남은 문자가 있습니다.");
            return v;
        }

        public static Dictionary<string, object> Obj(object o, string key) =>
            (o as Dictionary<string, object>)?.TryGetValue(key, out var v) == true ? v as Dictionary<string, object> : null;

        public static List<object> Arr(object o, string key) =>
            (o as Dictionary<string, object>)?.TryGetValue(key, out var v) == true ? v as List<object> : null;

        public static string Str(object o, string key) =>
            (o as Dictionary<string, object>)?.TryGetValue(key, out var v) == true && v != null ? Convert.ToString(v, CultureInfo.InvariantCulture) : null;

        public static bool Bool(object o, string key) =>
            (o as Dictionary<string, object>)?.TryGetValue(key, out var v) == true && v is bool b && b;

        static void Ws(string s, ref int i) { while (i < s.Length && char.IsWhiteSpace(s[i])) i++; }

        static object Value(string s, ref int i)
        {
            Ws(s, ref i);
            if (i >= s.Length) throw new FormatException("JSON이 끝났습니다.");
            char c = s[i];
            if (c == '{')
            {
                var d = new Dictionary<string, object>();
                i++; Ws(s, ref i);
                if (s[i] == '}') { i++; return d; }
                while (true)
                {
                    Ws(s, ref i);
                    string k = Str(s, ref i);
                    Ws(s, ref i); Expect(s, ref i, ':');
                    d[k] = Value(s, ref i);
                    Ws(s, ref i);
                    if (s[i] == ',') { i++; continue; }
                    Expect(s, ref i, '}');
                    return d;
                }
            }
            if (c == '[')
            {
                var l = new List<object>();
                i++; Ws(s, ref i);
                if (s[i] == ']') { i++; return l; }
                while (true)
                {
                    l.Add(Value(s, ref i));
                    Ws(s, ref i);
                    if (s[i] == ',') { i++; continue; }
                    Expect(s, ref i, ']');
                    return l;
                }
            }
            if (c == '"') return Str(s, ref i);
            if (s.Substring(i).StartsWith("true")) { i += 4; return true; }
            if (s.Substring(i).StartsWith("false")) { i += 5; return false; }
            if (s.Substring(i).StartsWith("null")) { i += 4; return null; }
            int st = i;
            while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
            return double.Parse(s.Substring(st, i - st), CultureInfo.InvariantCulture);
        }

        static void Expect(string s, ref int i, char c)
        {
            if (i >= s.Length || s[i] != c) throw new FormatException("'" + c + "' 이(가) 필요합니다(위치 " + i + ").");
            i++;
        }

        static string Str(string s, ref int i)
        {
            Expect(s, ref i, '"');
            var sb = new StringBuilder();
            while (s[i] != '"')
            {
                char c = s[i++];
                if (c != '\\') { sb.Append(c); continue; }
                char e = s[i++];
                switch (e)
                {
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'u': sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16)); i += 4; break;
                    default: sb.Append(e); break;
                }
            }
            i++;
            return sb.ToString();
        }
    }
}
