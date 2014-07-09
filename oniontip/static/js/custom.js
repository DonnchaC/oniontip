function addListener(){
    $('.sort').each(function(index, element) {
        var url = window.location;
        var origin = window.location.origin;
        var path = window.location.pathname;
        var args = parseArgs(url);
        args['sort'] = this.id;
        url = origin+path+'?'+$.param(args);
        $(this).attr('href', url);
    });
}


function doAjax(){
    var path = window.location.search;
    if(path) {
        $('.loading').show();
        $('html, body').animate({
            scrollTop: $('.loading').offset().top
        }, 1000);
        $.ajax({
            url: "result"+path,
            type: "GET",
        }).done(function(data) {
            $('.loading').hide();
            $('#result').append(data);
            $('html, body').animate({ 
                scrollTop: $('#result').offset().top
            }, 1000);
            $('span[rel=tooltip]').tooltip();
        });
    }
}

function parseArgs(query){
    var newQuery = {}, key, value;
    query = String(query);
    query = query.split("?")[1];
    query = query.split("&");
    $.each(query, function(i, arg){
        arg = arg.split("=");
        newQuery[arg[0]] = arg[1];
    });
    return newQuery;
}

function setOptions(){
    var path = window.location.search;
    if (path) {
        var args = parseArgs(path);
        $.each(args, function (arg, value) {
            type = ($('input.'+arg).attr("type") || $('input#'+arg).attr("type"));
            if (type == "checkbox" || type == "radio") {
                $('input.'+arg).val([value]);
                $('input#'+arg).val([value]);
            } else if( type == "text") {
                $('input.'+arg).val(value);
                $('input#'+arg).val(value);
            }
        });
    }
}