// Javascript functions to the Popular Images page

function defer(method) {
    if (window.jQuery) {
        // Show modal on click the remove image button
        $(document).on('click', '.removePopularImageBtn', function() {
            var image_id = $(this).val();

            // Set a red border to alert the user that the image will be removed.
            document.getElementById(image_id).style.border="5px solid red";

            // Set the image id to the modal data attribute. To be used on the modal close event.
            document.getElementById('removePopularImageModal').setAttribute("data-image_id", image_id);

            // Set the form action to the image id.
            $('#removePopularImageForm').attr('action', '/explore/popular-images/remove/'+image_id+'/');

            // Set page number for the view to redirect back to the same page after image removal.
            let searchParams = new URLSearchParams(window.location.search)
            searchParams.has('page')
            let page = searchParams.get('page')
            $('input[name="page"]').val(page);

        });

        // Close modal - Ignore remove action
        $("#removePopularImageModal").on("hide.bs.modal", function () {
            image_id = document.getElementById("removePopularImageModal").dataset.image_id
            document.getElementById(image_id).style.border="none";
        });
    } else {
        setTimeout(function() { defer(method) }, 50);
    }
}
// To wait for JQuery to load.
defer(function () {});
