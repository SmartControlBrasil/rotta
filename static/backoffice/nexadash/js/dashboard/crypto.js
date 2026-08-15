

(function($) {
    /* "use strict" */
	
 var dzChartlist = function(){
	
	var screenWidth = $(window).width();
	let draw = Chart.controllers.line.__super__.draw; //draw shadow
		var handleWebpicker = function(){
			$('#crypto-webticker').webTicker({
				height:'auto', 
				duplicate:true, 
				startEmpty:false, 
				rssfrequency:4
			});
		}
		var activityChart = function(){
			var activity = document.getElementById("activity");
			
				if (activity !== null) {
					var activityData = [{
							first: [ 3000, 3500, 3000, 4000, 4000, 3000, 4000, 4000,3000, 4000, 4500],
							second: [ 2500, 4000, 3500, 4500, 3800, 3500, 3800, 3500,3500, 3800, 4000],
							third: [ 30, 25, 30, 40, 40, 30,18, 20,30,18, 20]
						},
						{
							first: [ 35, 35, 40, 30, 38, 40, 50, 38,40, 50, 38],
							second: [ 38, 38, 38, 28, 40, 38, 45, 30,30, 25, 30],
							third: [ 35, 40, 30, 30, 35, 40, 35, 32,30, 25, 32]
						},
						{
							first: [ 35, 35, 40, 30, 38, 50, 60, 38,40, 50, 38],
							second: [ 38, 38, 38, 28, 40, 28, 35, 30,30, 25, 30],
							third: [ 35, 40, 30, 30, 35, 30, 45, 32,30, 25, 32]
						},
					];
					activity.height = 400;
					
					var config = {
						type: "line",
						data: {
							labels: [
								"10:59PM",
								"11:59PM",
								"12:59AM",
								"1:59AM",
								"2:59AM",
								"3:59AM",
								"4:59AM",
								"5:59AM",
								"6:59AM",
								"7:59AM",
							],
							datasets: [{
									label: "Active",
									backgroundColor: "rgba(28, 28, 28, 0)",
									borderColor: "#1C1C1C",
									data: activityData[0].first,
									borderWidth: 1.972,
									tension: 0.5,
								},
								{
									label: "Inactive",
									backgroundColor: 'rgba(255, 142, 38, 0)',
									borderColor: "#1D69D6",
									data: activityData[0].second,
									borderWidth: 1.972,
									tension: 0.5,
									
								},
							]
						},
						options: {
							responsive: true,
							maintainAspectRatio: false,
							
							elements: {
									point:{
										radius: 0
									}
							},
							plugins:{
								legend: false,
							},
							scales: {
								y: {
									grid: {
										color: "rgba(233,236,255,0.5)",
										drawBorder: true
									},
									ticks: {
										fontSize: 14,
										fontColor: "#6E6E6E",
										fontFamily: "Poppins"
									},
								},
								x: {
									//FontSize: 40,
									grid: {
										display: false,
										zeroLineColor: "white"
									},
									ticks: {
										fontSize: 14,
										stepSize: 5,
										fontColor: "#6E6E6E",
										fontFamily: "Poppins"
									}
								}
							},
							tooltips: {
								enabled: false,
								mode: "index",
								intersect: false,
								titleFontColor: "#888",
								bodyFontColor: "#555",
								titleFontSize: 12,
								bodyFontSize: 15,
								backgroundColor: "rgba(256,256,256,0.95)",
								displayColors: true,
								xPadding: 10,
								yPadding: 7,
								borderColor: "rgba(220, 220, 220, 0.9)",
								borderWidth: 2,
								caretSize: 6,
								caretPadding: 10
							}
						}
						
					};
					var activity = new Chart(activity, config);
					var element = document.querySelector('body');
					var observer = new MutationObserver(function(mutations) {
						mutations.forEach(function(mutation) {
							if(mutation.attributeName === "data-theme-version"){
								if($('body').attr('data-theme-version') === "dark"){
									config.options.scales.y.grid.color = '#3d3d4e'
									config.options.scales.x.grid.color = '#3d3d4e'
								}else{
									config.options.scales.y.grid.color = '#eee'
									config.options.scales.x.grid.color = '#eee'
								}
								activity.update();
							}
						});
					});
					observer.observe(element, {
						attributes: true
					});
					

					var ctx = document.getElementById("activity").getContext("2d");
					var myLine = new Chart(ctx, config);

					var items = document.querySelectorAll("#user-activity .nav-pills .nav-item");
					items.forEach(function(item, index) {
						item.addEventListener("click", function() {
							config.data.datasets[0].data = activityData[index].first;
							config.data.datasets[1].data = activityData[index].second;
							myLine.update();
						});
					});
				}
		
			
		}

	
	
	
	
	
 
	/* Function ============ */
		return {
			init:function(){
			},
			
			
			load:function(){
				handleWebpicker();
				activityChart();
				
			},
			
			resize:function(){
				
			}
		}
	
	}();

	
		
	jQuery(window).on('load',function(){
		setTimeout(function(){
			dzChartlist.load();
		}, 1000); 
		
	});

     

})(jQuery);
