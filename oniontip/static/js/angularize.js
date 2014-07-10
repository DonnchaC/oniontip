var oniontipModule = angular.module("OnionTip", ['ui','oblique.directives','oblique.filters'])

oniontipModule.value('ui.config', {
   select2: {
      allowClear: true,
      width: "element",
   }
});

oniontipModule.controller('OnionTipCtrl',function OnionTipCtrl($scope,$http,$location) {

  $scope.state = "hidden"
  $scope.query = {
    exit_filter:"all_relays",
    links:true,
    sort:'cw',
    sort_reverse: true,
    country: null
  }
  $scope.payment_address = '';
  $scope.last_refreshed = '-'

  /** Watch the location bar to allow us to load saved searches **/
  $scope.$watch($location.search(), function(newv, oldv, scope) {
    if ($location.search().top) {
      $scope.query=$location.search()
      $scope.request()
    }
  })

  function bootstrap_alert(elem, type, message, timeout) {
    $(elem).show().html('<div class="alert alert-dismissible alert-'+type+'"><button type="button" class="close" data-dismiss="alert" aria-hidden="true">&times;</button><small>'+message+'</small></div>');

    if (timeout || timeout === 0) {
      setTimeout(function() { 
        $(elem).alert('close');
      }, timeout);    
    }
  };

  /** Make a sorting request
   *
   * Call 'success_cb' if the request is successful
   */
  $scope.ajax_sort = function(sortBy, invert, success_cb) {
    $scope.query.sort = sortBy
    $scope.query.sort_reverse = invert

    //Update the location bar to track sorting
    $location.search($scope.query)

    $http.get('result.json',{"params":$scope.query})
      .success(function(data) {
        if (data.results.length > 0) {
          $scope.data = data

          if (success_cb !== null){
            success_cb()
          }

          $('body').animate({scrollTop:$("div#result_table").offset().top},500)
        }
        else {
          $scope.state = "result_empty"
        }
      })

  }

  /**  Make a data request from the form
   *
   * Call 'success_cb' if the request is successful
   */
  $scope.request = function(success_cb) {
    $scope.state = 'loading'
    //Set the location bar for this search
    $location.search($scope.query)

    $http.get('result.json',{"params":$scope.query})
      .success(function(data) {
        $('#last_refreshed').text(data.relays_published);
        if (data.results.length > 0) {
          $scope.data = data
          $scope.state = "loaded"
          if (success_cb != null){
            success_cb()
          }
          $('body').animate({scrollTop:$("div#result_table").offset().top},500)
          $('#routerlisting').collapse('show');
        }
        else {
          $scope.state = "result_empty"
        }
      })
  };

  /**  Make a data request from the form to generate payment info
   *
   * Call 'success_cb' if the request is successful
   */
  $scope.donate = function(success_pay) {
    $scope.state = 'loading'
    $http.get('payment.json',{"params":$scope.query})
      .success(function(response) {
        if (response.data.bitcoin_address) {
          $scope.payment_address = response.data.bitcoin_address
          $scope.state = "loaded"
          if (success_pay != null){
            success_pay()
          }
          //$('body').animate({scrollTop:$("div#result_table").offset().top},500)
        }
        else {
          $scope.state = "result_empty"
        }
        $("#payment_errors .alert").remove(); // Remove previously shown alerts 
        $("#paymentModal").modal("show");
      })
  };

  /**  Check transaction **/
  $scope.checktx = function(bitcoin_address) {
    $scope.state = 'loading';
    $http.get('forward/'+bitcoin_address)
      .success(function(response) {
        $scope.state = 'success'
        bootstrap_alert('#payment_errors', 'success', response.data.message);
      }).
      error(function(response, status) {
        $scope.state = 'warn'
        if(response.status == 'fail'){
          bootstrap_alert('#payment_errors', 'warning', response.data.message);
        } else if(response.status == 'error'){
          bootstrap_alert('#payment_errors', 'warning', '<strong>Error '+status+'</strong>: '+response.message);
        } else {
          if(status == 408 || status == 522){
            bootstrap_alert('#payment_errors', 'warning', '<strong>Request Timeout</strong>: Blockchain.info may be down, please try again in a few moments.</strong>');
          } else {
            bootstrap_alert('#payment_errors', 'warning', '<strong>Error '+status+'</strong>: An unknown error occured</strong>');
          }
        }
      });
  };

  $http.get("static/data/cc.json").success(function(data) {
    $scope.cc_data = data
  })

  $scope.country_select = {
    allowClear: true,
    width: "element",
  }

})
