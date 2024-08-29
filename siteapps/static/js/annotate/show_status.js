function showStatusFailure() {
    $(".spinner-border").hide();
    $("#status-failure").removeClass("d-none");
    setTimeout(function(){
        $("#status-failure").addClass("d-none");
    }, 10000);
}

function showStatusSuccess() {
    $(".spinner-border").hide();
    $("#status-success").removeClass("d-none");
    setTimeout(function(){
        $("#status-success").addClass("d-none");
    }, 10000);
}
