st, regex = Regex.new("^CONNECT ([A-Za-z0-9.-]+):([0-9]+) HTTP/1", true);

function hproxy(txn)
    line = txn.req:getline()
    core.Debug(line)
    st, list = regex:match(line)
    if not st then return end
    host, port = list[2], list[3];
    repeat line = txn.req:getline() until #line <= 2 -- crlf
    txn:set_var('txn.host', host)
    txn:set_var('txn.port', port)
    txn.res:send('HTTP/1.1 200 OK\r\n\r\n')
    core.Debug(string.format('host=%s port=%s', host, port))
end

core.register_action("hproxy", {"tcp-req"}, hproxy, 0)
