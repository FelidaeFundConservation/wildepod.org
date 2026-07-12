/*
 * Copyright (c) 2026 Felidae Conservation Fund info@felidaefund.org
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

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
